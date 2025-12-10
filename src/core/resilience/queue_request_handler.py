"""
Queue Request Handler - Third Layer of Defense (Distributed)

This module provides the bridge between the streaming API routes and the
message queue system (Redis/Kafka). When the connection pool is exhausted,
requests are queued here instead of returning 429 errors.

ARCHITECTURE UPDATE (v2):
=========================
Originally used process-local Futures, but this fails in distributed Docker
deployments where the consumer worker might be on a different instance than
the request handler.

DISTRIBUTED PATTERN (Pub/Sub):
==============================
1. Publisher (This module):
   - Generates request_id
   - Subscribes to Redis channel: `queue:results:{request_id}`
   - Queues request to Redis Stream
   - Yields events as they arrive on the channel

2. Consumer Worker (Remote):
   - Processes request
   - PUBLISHES chunks to `queue:results:{request_id}`
   - PUBLISHES "DONE" or "ERROR" signal

This enables TRUE STREAMING even during failover!

Author: Senior Solution Architect
Date: 2025-12-09
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger
from src.infrastructure.cache.redis_client import get_redis_client
from src.infrastructure.message_queue.factory import get_message_queue
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class QueuedRequestStatus(Enum):
    """Status of a queued streaming request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class QueuedStreamingRequest:
    """Represents a streaming request waiting in the queue."""
    request_id: str
    user_id: str
    thread_id: str
    payload: dict[str, Any]
    enqueue_time: float = field(default_factory=time.time)
    retry_count: int = 0
    status: QueuedRequestStatus = QueuedRequestStatus.PENDING

    def to_dict(self) -> dict:
        """Serialize to dictionary for queue storage."""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "payload": self.payload,
            "enqueue_time": self.enqueue_time,
            "retry_count": self.retry_count,
            "status": self.status.value
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueuedStreamingRequest":
        """Deserialize from dictionary."""
        return cls(
            request_id=data["request_id"],
            user_id=data["user_id"],
            thread_id=data["thread_id"],
            payload=data["payload"],
            enqueue_time=data.get("enqueue_time", time.time()),
            retry_count=data.get("retry_count", 0),
            status=QueuedRequestStatus(data.get("status", "pending"))
        )


# =============================================================================
# QUEUE REQUEST HANDLER (DISTRIBUTED)
# =============================================================================

class QueueRequestHandler:
    """
    Handles queueing of streaming requests with distributed response streaming.

    Uses Redis Pub/Sub to receive streamed chunks from remote workers.
    """

    QUEUE_TOPIC = "streaming_requests_failover"
    RESULT_CHANNEL_PREFIX = "queue:results:"

    def __init__(self):
        """Initialize the queue request handler."""
        self.settings = get_settings()
        self._queue = None
        self._redis = None
        self._initialized = False
        self._metrics = get_metrics_collector()

        self.enabled = getattr(self.settings, 'QUEUE_FAILOVER_ENABLED', True)
        self.timeout_seconds = getattr(
            self.settings, 'QUEUE_FAILOVER_TIMEOUT_SECONDS', 30
        )

        logger.info(
            "Queue request handler configured (Distributed)",
            stage="LAYER3.INIT",
            enabled=self.enabled
        )

    async def initialize(self) -> None:
        """Initialize connections."""
        if self._initialized:
            return

        self._queue = get_message_queue(
            topic=self.QUEUE_TOPIC,
            group_name="streaming_failover_consumers"
        )
        await self._queue.initialize()

        # Get Redis client for Pub/Sub
        self._redis = get_redis_client()
        await self._redis.connect()

        self._initialized = True

    async def queue_and_stream(
        self,
        user_id: str,
        thread_id: str,
        payload: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """
        Queue request and yield streamed chunks via Redis Pub/Sub.

        FLOW:
        -----
        1. Generate Request ID
        2. Subscribe to Redis channel `queue:results:{id}`
        3. Queue request to Redis Stream
        4. Yield messages received on channel
        5. Unsubscribe when DONE signal received

        Yields:
             SSE formatted event strings
        """
        if not self.enabled:
            raise RuntimeError("Queue failover disabled")

        await self.initialize()

        # 1. Generate ID
        request_id = f"qr-{uuid.uuid4().hex[:12]}"
        channel_name = f"{self.RESULT_CHANNEL_PREFIX}{request_id}"

        # 2. Subscribe FIRST (to not miss early events)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel_name)

        # 3. Queue Request
        queued_request = QueuedStreamingRequest(
            request_id=request_id,
            user_id=user_id,
            thread_id=thread_id,
            payload=payload
        )

        try:
            # =========================================================================
            # MECHANISM EXPLANATION: Enqueueing Strategy
            # =========================================================================
            # 1. We wrap the request payload into a standardized dictionary
            # 2. We push this payload to the configured Message Queue (Redis/Kafka)
            # 3. We DO NOT wait for the worker to pick it up here.
            # 4. Instead, we immediately start listening to the "result channel" (Pub/Sub)
            #
            # The worker process (running independently) will:
            # - Pop this message from the queue
            # - Process it
            # - Publish results back to the channel we are listening to

            queue_key = (
                self._queue.queue_name
                if hasattr(self._queue, 'queue_name')
                else self.QUEUE_TOPIC
            )

            # LOGGING REQUIREMENT: Show exactly where the data is going
            logger.info(
                f"[QUEUE-PRODUCER] Pushing request to queue: {queue_key}",
                stage="LAYER3.ENQUEUE",
                request_id=request_id,
                queue_type=self.settings.QUEUE_TYPE,  # 'redis' or 'kafka'
                queue_key=queue_key,                  # Redis Key or Kafka Topic
                payload_size=len(str(queued_request.to_dict()))
            )

            await self._queue.produce(queued_request.to_dict())
            self._metrics.record_queue_produce_attempt("failover")

            logger.info(
                "Request successfully queued, now listening for stream response...",
                stage="LAYER3.STREAM_WAIT",
                request_id=request_id,
                channel=channel_name
            )

            # 4. Stream Loop
            # We must implement timeout manually since we're in a loop
            start_time = time.time()
            last_ping_time = time.time()
            # Keep connection alive (NGINX proxy_read_timeout often 60s)
            ping_interval = 15.0

            while True:
                current_time = time.time()

                # Check timeout
                if current_time - start_time > self.timeout_seconds:
                    logger.warning("Queue stream timeout", request_id=request_id)
                    error_data = json.dumps({"error": "Queue timeout - server busy"})
                    yield f"event: error\ndata: {error_data}\n\n"
                    break

                # HEARTBEAT: Keep connection alive
                if current_time - last_ping_time > ping_interval:
                    # SSE comment ping (keeps socket open)
                    yield ": ping\n\n"
                    last_ping_time = current_time
                    logger.debug("Queue stream heartbeat", request_id=request_id)

                # Get message (non-blocking with small sleep)
                message = await pubsub.get_message(ignore_subscribe_messages=True)

                if message:
                    # Reset ping timer on activity
                    last_ping_time = current_time

                    # Message data is bytes or str
                    data = message['data']
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')

                    # Check for signals
                    if data == "SIGNAL:DONE":
                        logger.info("Stream complete signal received", request_id=request_id)
                        break
                    elif data.startswith("SIGNAL:ERROR:"):
                        error_msg = data.replace("SIGNAL:ERROR:", "")
                        logger.error("Stream error signal received", error=error_msg)
                        yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                        break

                    # It's a chunk! Yield it
                    yield data

                    # Reset timeout on activity
                    # start_time = time.time() # Optional: sliding timeout
                else:
                    await asyncio.sleep(0.01)

        except Exception as e:
            logger.error("Queue stream failed", error=str(e))
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        finally:
            # 5. Cleanup
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
            logger.info("Queue stream closed", request_id=request_id)


_handler_instance: QueueRequestHandler | None = None

def get_queue_request_handler() -> QueueRequestHandler:
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = QueueRequestHandler()
    return _handler_instance
