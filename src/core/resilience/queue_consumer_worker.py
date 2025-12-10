"""
Queue Consumer Worker - Distributed Streaming Publisher

This module provides a background worker that processes streaming requests
and PUBLISHES the chunks back to the requester via Redis Pub/Sub.

ARCHITECTURE UPDATE (v2):
=========================
Instead of resolving Futures (which only works locally), this worker now
streams the LLM response chunk-by-chunk to a Redis Channel.

FLOW:
-----
1. Consume message from Queue
2. Process with StreamOrchestrator
3. As each chunk arrives → PUBLISH to `queue:results:{request_id}`
4. When done → PUBLISH `SIGNAL:DONE`

This allows the request handler (on any instance) to stream the response
in real-time to the user.

Author: Senior Solution Architect
Date: 2025-12-09
"""

import asyncio
import socket
import time
from collections.abc import Callable

from src.core.config.settings import get_settings
from src.core.exceptions.connection_pool import (
    ConnectionPoolExhaustedError,
    UserConnectionLimitError,
)
from src.core.interfaces.message_queue import QueueMessage
from src.core.logging.logger import get_logger
from src.core.resilience.connection_pool_manager import get_connection_pool_manager
from src.core.resilience.queue_request_handler import (
    QueuedStreamingRequest,
)
from src.infrastructure.cache.redis_client import get_redis_client
from src.infrastructure.message_queue.factory import get_message_queue
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


class QueueConsumerWorker:
    """
    Background worker that processes queued requests and streams results via Redis.
    """

    QUEUE_TOPIC = "streaming_requests_failover"
    RESULT_CHANNEL_PREFIX = "queue:results:"

    def __init__(self, stream_processor: Callable | None = None):
        self.settings = get_settings()
        self._queue = None
        self._redis = None
        self._running = False
        self._metrics = get_metrics_collector()
        self._stream_processor = stream_processor

        self._pool_manager = get_connection_pool_manager()

        # Configuration
        self.max_retries = getattr(self.settings, 'QUEUE_FAILOVER_MAX_RETRIES', 5)
        self.timeout_seconds = getattr(self.settings, 'QUEUE_FAILOVER_TIMEOUT_SECONDS', 30)
        self.base_delay_ms = getattr(self.settings, 'QUEUE_FAILOVER_BASE_DELAY_MS', 100)

        self._consumer_name = f"worker-{socket.gethostname()}-{id(self)}"

    async def initialize(self) -> None:
        """Initialize connections."""
        self._queue = get_message_queue(
            topic=self.QUEUE_TOPIC,
            group_name="streaming_failover_consumers"
        )
        await self._queue.initialize()

        self._redis = get_redis_client()
        await self._redis.connect()

        logger.info("Consumer worker ready (Distributed Pub/Sub)", consumer=self._consumer_name)

    async def start(self) -> None:
        """Start consumer loop."""
        await self.initialize()
        self._running = True

        logger.info("Starting consumer loop", consumer=self._consumer_name)

        while self._running:
            try:
                messages = await self._queue.consume(
                    consumer_name=self._consumer_name,
                    batch_size=5, # Smaller batch for streaming responsiveness
                    block_ms=2000
                )

                for message in messages:
                    # Process concurrently? For now, sequential to respect pool limits cleanly
                    await self._process_message(message)

                if not messages:
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("Consumer loop error", error=str(e))
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False

    async def _process_message(self, message: QueueMessage) -> None:
        """Process message and stream results to Redis channel."""
        try:
            request = QueuedStreamingRequest.from_dict(message.payload)
            channel = f"{self.RESULT_CHANNEL_PREFIX}{request.request_id}"

            # Check timeout
            if time.time() - request.enqueue_time > self.timeout_seconds:
                # Timed out - ignore
                await self._queue.acknowledge(message.id)
                return

            # Acquire connection
            connection_acquired = False
            try:
                # MECHANISM EXPLANATION: Dequeue & Process
                # ----------------------------------------
                # We have popped a message from the queue (Redis List or Kafka Topic).
                # Now we must acquire a connection slot to process it.
                # If the pool is STILL full, we will:
                # 1. Release the message (nack) OR
                # 2. Re-queue it with backoff (handle_retry)

                queue_source = (
                    self._queue.queue_name
                    if hasattr(self._queue, 'queue_name')
                    else self.QUEUE_TOPIC
                )

                logger.info(
                    f"[QUEUE-CONSUMER] Popped request from: {queue_source}",
                    stage="LAYER3.DEQUEUE",
                    request_id=request.request_id,
                    queue_type=self.settings.QUEUE_TYPE,
                    queue_source=queue_source,
                    processing_start=time.time()
                )

                await self._pool_manager.acquire_connection(request.user_id, request.thread_id)
                connection_acquired = True

                logger.info(
                    "Connection acquired for queued request - starting stream processing",
                    id=request.request_id
                )

                # EXECUTE STREAM
                # We need to capture the generator and publish chunks

                # 1. Get Orchestrator
                from src.llm_stream.services.stream_orchestrator import get_stream_orchestrator
                orchestrator = get_stream_orchestrator()

                # 2. Iterate and Publish
                async for event in orchestrator.stream(
                    query=request.payload.get("query", ""),
                    model=request.payload.get("model", "gpt-3.5-turbo"),
                    provider=request.payload.get("provider", "fake"),
                    user_id=request.user_id
                ):
                    # Publish chunk to Redis Channel
                    # Event is already an SSE formatted string
                    await self._redis.publish(channel, event)

                # 3. Done Signal
                await self._redis.publish(channel, "SIGNAL:DONE")

                # Success!
                await self._queue.acknowledge(message.id)
                self._metrics.record_queue_consume_success("failover")

            except (UserConnectionLimitError, ConnectionPoolExhaustedError):
                # Retry logic
                if connection_acquired:
                    await self._pool_manager.release_connection(request.user_id, request.thread_id)
                    connection_acquired = False

                await self._handle_retry(message, request)

            except Exception as e:
                logger.error("Error processing stream", error=str(e))
                await self._redis.publish(channel, f"SIGNAL:ERROR:{str(e)}")
                # Acknowledge to prevent poison pill loop
                await self._queue.acknowledge(message.id)

            finally:
                if connection_acquired:
                    await self._pool_manager.release_connection(request.user_id, request.thread_id)

        except Exception as e:
            logger.error("Fatal worker error", error=str(e))

    async def _handle_retry(self, message: QueueMessage, request: QueuedStreamingRequest) -> None:
        """Handle retry backoff."""
        if request.retry_count >= self.max_retries:
            channel = f"{self.RESULT_CHANNEL_PREFIX}{request.request_id}"
            await self._redis.publish(channel, "SIGNAL:ERROR:Max retries exceeded")
            await self._queue.acknowledge(message.id)
            return

        # Backoff
        delay = min(self.base_delay_ms * (2 ** request.retry_count), 5000)
        await asyncio.sleep(delay / 1000.0)

        # Re-queue
        request.retry_count += 1
        await self._queue.produce(request.to_dict())
        await self._queue.acknowledge(message.id)


# Global instances (same pattern as before)
_worker_instance: QueueConsumerWorker | None = None
_worker_task: asyncio.Task | None = None

async def start_queue_consumer_worker() -> QueueConsumerWorker:
    global _worker_instance, _worker_task
    if _worker_instance is None:
        _worker_instance = QueueConsumerWorker()
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_instance.start())
    return _worker_instance

async def stop_queue_consumer_worker() -> None:
    global _worker_instance, _worker_task
    if _worker_instance:
        _worker_instance.stop()
    if _worker_task:
        await asyncio.wait([_worker_task], timeout=5.0)
    _worker_instance = None
    _worker_task = None
