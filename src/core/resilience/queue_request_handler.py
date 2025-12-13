"""
Queue Request Handler - Distributed Streaming via Redis Pub/Sub

Bridges streaming API routes with message queue system for failover.
When connection pool exhausted, queues requests and streams results via Pub/Sub.

Architecture:
    QueueRequestHandler (Public API)
        ├── RequestEnqueuer (Queue operations)
        ├── StreamSubscriber (Redis Pub/Sub subscription)
        ├── EventStreamer (SSE event streaming)
        └── HeartbeatManager (Keep-alive management)

Flow:
    1. Generate request_id
    2. Subscribe to Redis channel: queue:results:{request_id}
    3. Enqueue request to message queue
    4. Stream events as they arrive on channel
    5. Handle completion/error signals

This enables TRUE STREAMING even during failover across distributed instances.

Author: Refactored for clarity and maintainability
Date: 2025-12-13
"""

import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import orjson

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger
from src.infrastructure.cache.redis_client import RedisClient, get_redis_client
from src.infrastructure.message_queue.base import MessageQueue
from src.infrastructure.message_queue.factory import get_message_queue
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION & DATA STRUCTURES
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
    """
    Represents a streaming request waiting in the queue.

    Serializable for queue storage and cross-instance communication.
    """
    request_id: str
    user_id: str
    thread_id: str
    payload: dict[str, Any]
    enqueue_time: float = field(default_factory=time.time)
    retry_count: int = 0
    status: QueuedRequestStatus = QueuedRequestStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> "QueuedStreamingRequest":
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


@dataclass
class StreamConfig:
    """Configuration for streaming behavior."""
    timeout_seconds: int = 30
    ping_interval_seconds: float = 15.0
    min_poll_interval_seconds: float = 0.1


# =============================================================================
# LAYER 1: REQUEST ENQUEUEING
# Handles pushing requests to message queue
# =============================================================================

class RequestEnqueuer:
    """
    Enqueues streaming requests to message queue.

    Responsibility:
        Handles queue production and logging of queue destinations.
        Supports both Redis and Kafka queue backends.

    Queue Destinations:
        Redis: queue:streaming_requests_failover (Redis Stream)
        Kafka: streaming_requests_failover (Kafka Topic)
    """

    QUEUE_TOPIC = "streaming_requests_failover"
    CONSUMER_GROUP = "streaming_failover_consumers"

    def __init__(self, queue: MessageQueue, metrics, settings):
        self._queue = queue
        self._metrics = metrics
        self._settings = settings

    async def enqueue(
        self,
        request_id: str,
        user_id: str,
        thread_id: str,
        payload: dict[str, Any],
    ) -> QueuedStreamingRequest:
        """
        Enqueue streaming request to message queue.

        Args:
            request_id: Unique request identifier
            user_id: User identifier
            thread_id: Thread identifier
            payload: Request payload (query, model, provider, etc.)

        Returns:
            QueuedStreamingRequest with metadata

        Queue Mechanism:
            1. Wrap request in standardized dictionary
            2. Push to configured message queue (Redis Stream or Kafka)
            3. Return immediately (don't wait for worker)
            4. Worker will process and publish results to Pub/Sub channel

        Queue Format:
            Redis: XADD to stream with max length 10,000
            Kafka: JSON message to topic with auto-partitioning
        """
        request = QueuedStreamingRequest(
            request_id=request_id,
            user_id=user_id,
            thread_id=thread_id,
            payload=payload,
        )

        # Determine queue destination for logging
        queue_key = (
            self._queue.queue_name
            if hasattr(self._queue, 'queue_name')
            else self.QUEUE_TOPIC
        )

        logger.info(
            "Enqueueing streaming request to queue",
            stage="ENQUEUE",
            request_id=request_id,
            queue_type=self._settings.QUEUE_TYPE,
            queue_key=queue_key,
            consumer_group=self.CONSUMER_GROUP,
            payload_size=len(str(request.to_dict())),
        )

        # Push to queue
        await self._queue.produce(request.to_dict())
        self._metrics.record_queue_produce_attempt("failover")

        logger.info(
            "Request successfully queued",
            stage="ENQUEUE_SUCCESS",
            request_id=request_id,
        )

        return request


# =============================================================================
# LAYER 2: REDIS PUB/SUB SUBSCRIPTION
# Manages Redis channel subscription lifecycle
# =============================================================================

class StreamSubscriber:
    """
    Manages Redis Pub/Sub subscription for streaming results.

    Responsibility:
        Subscribes to result channels.
        Provides async iterator for receiving messages.
        Handles subscription lifecycle and cleanup.
    """

    RESULT_CHANNEL_PREFIX = "queue:results:"

    def __init__(self, redis: RedisClient):
        self._redis = redis
        self._pubsub = None
        self._channel_name = None

    def get_channel_name(self, request_id: str) -> str:
        """Generate channel name for request."""
        return f"{self.RESULT_CHANNEL_PREFIX}{request_id}"

    async def subscribe(self, request_id: str) -> None:
        """
        Subscribe to result channel for request.

        Must be called BEFORE enqueueing to avoid missing early events.

        Args:
            request_id: Unique request identifier
        """
        self._channel_name = self.get_channel_name(request_id)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel_name)

        logger.info(
            "Subscribed to result channel",
            stage="SUBSCRIBE",
            request_id=request_id,
            channel=self._channel_name,
        )

    async def get_message(self, timeout: float) -> dict[str, Any] | None:
        """
        Get message from subscription with timeout.

        Blocks efficiently on server-side until message arrives or timeout.

        Args:
            timeout: Maximum seconds to wait for message

        Returns:
            Message dict or None if timeout

        Performance Note:
            This uses server-side blocking (BLPOP-style) instead of
            client-side polling, reducing CPU usage by ~90% when idle.
        """
        if not self._pubsub:
            raise RuntimeError("Not subscribed. Call subscribe() first.")

        return await self._pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=timeout,
        )

    async def unsubscribe(self) -> None:
        """Unsubscribe from channel and cleanup."""
        if self._pubsub:
            if self._channel_name:
                await self._pubsub.unsubscribe(self._channel_name)
            await self._pubsub.close()

            logger.info(
                "Unsubscribed from result channel",
                stage="UNSUBSCRIBE",
                channel=self._channel_name,
            )


# =============================================================================
# LAYER 3: HEARTBEAT MANAGEMENT
# Manages SSE keep-alive pings
# =============================================================================

class HeartbeatManager:
    """
    Manages SSE heartbeat pings to keep connection alive.

    Responsibility:
        Tracks last activity time.
        Determines when to send heartbeat.
        Generates SSE ping messages.

    Rationale:
        NGINX and other proxies often have 60s read timeouts.
        Sending pings every 15s keeps connection alive during
        slow processing or queue wait times.
    """

    def __init__(self, ping_interval_seconds: float = 15.0):
        self._ping_interval = ping_interval_seconds
        self._last_activity_time = time.time()

    def record_activity(self) -> None:
        """Record activity (message received)."""
        self._last_activity_time = time.time()

    def should_send_ping(self) -> bool:
        """
        Check if heartbeat ping should be sent.

        Returns:
            True if time since last activity exceeds ping interval
        """
        return (time.time() - self._last_activity_time) > self._ping_interval

    def get_ping_message(self) -> str:
        """
        Generate SSE heartbeat ping message.

        Returns:
            SSE comment line (keeps connection alive without sending event)
        """
        return ": ping\n\n"

    def time_until_next_ping(self) -> float:
        """
        Calculate seconds until next ping needed.

        Returns:
            Seconds until ping should be sent (may be negative if overdue)
        """
        elapsed = time.time() - self._last_activity_time
        return self._ping_interval - elapsed


# =============================================================================
# LAYER 4: EVENT STREAMING
# Processes messages and generates SSE events
# =============================================================================

class EventStreamer:
    """
    Processes Pub/Sub messages and generates SSE events.

    Responsibility:
        Parses message types (data, signals, batches).
        Generates SSE-formatted strings.
        Handles error formatting.

    Message Types:
        - "SIGNAL:DONE" → Stream complete
        - "SIGNAL:ERROR:..." → Error occurred
        - "BATCH:[...]" → Batched chunks (optimization)
        - Other → Single SSE chunk
    """

    async def process_message(
        self,
        message: dict[str, Any],
        request_id: str,
    ) -> tuple[list[str], bool]:
        """
        Process Pub/Sub message and generate SSE events.

        Args:
            message: Message from Redis Pub/Sub
            request_id: Request identifier for logging

        Returns:
            Tuple of (events, should_stop) where:
                events: List of SSE-formatted strings to yield
                should_stop: True if stream should end

        Message Handling:
            SIGNAL:DONE → Empty list + stop
            SIGNAL:ERROR:msg → Error event + stop
            BATCH:[...] → List of chunks + continue
            Other → Single chunk + continue
        """
        # Decode message data
        data = message['data']
        if isinstance(data, bytes):
            data = data.decode('utf-8')

        # Handle completion signal
        if data == "SIGNAL:DONE":
            logger.info(
                "Stream complete signal received",
                stage="SIGNAL_DONE",
                request_id=request_id,
            )
            return [], True

        # Handle error signal
        if data.startswith("SIGNAL:ERROR:"):
            error_msg = data.replace("SIGNAL:ERROR:", "")
            logger.error(
                "Stream error signal received",
                stage="SIGNAL_ERROR",
                request_id=request_id,
                error=error_msg,
            )

            error_event = self._format_error_event(error_msg)
            return [error_event], True

        # Handle batched chunks
        if data.startswith("BATCH:"):
            return await self._process_batch(data, request_id), False

        # Single chunk (backward compatibility)
        return [data], False

    async def _process_batch(
        self,
        data: str,
        request_id: str,
    ) -> list[str]:
        """
        Process batched chunks.

        Worker batches chunks to reduce Redis Pub/Sub overhead.
        We receive: "BATCH:["chunk1", "chunk2", ...]"
        We parse and return individual chunks.

        Args:
            data: BATCH: prefixed JSON array string
            request_id: Request identifier for logging

        Returns:
            List of individual chunk strings
        """
        batch_json = data.replace("BATCH:", "")

        try:
            chunk_batch = orjson.loads(batch_json)

            logger.debug(
                "Received chunk batch",
                stage="BATCH_RECEIVE",
                request_id=request_id,
                batch_size=len(chunk_batch),
            )

            return chunk_batch

        except (ValueError, orjson.JSONDecodeError) as e:
            logger.error(
                "Failed to parse chunk batch",
                stage="BATCH_PARSE_ERROR",
                request_id=request_id,
                error=str(e),
            )
            # Return empty list - don't break stream
            return []

    def _format_error_event(self, error: str) -> str:
        """
        Format error as SSE event.

        Args:
            error: Error message

        Returns:
            SSE-formatted error event
        """
        error_data = orjson.dumps({"error": error}).decode('utf-8')
        return f"event: error\ndata: {error_data}\n\n"

    def format_timeout_error(self) -> str:
        """
        Format timeout error as SSE event.

        Returns:
            SSE-formatted timeout error event
        """
        return self._format_error_event("Queue timeout - server busy")

    def format_exception_error(self, exception: Exception) -> str:
        """
        Format exception as SSE error event.

        Args:
            exception: Exception that occurred

        Returns:
            SSE-formatted error event
        """
        return self._format_error_event(str(exception))


# =============================================================================
# LAYER 5: STREAM ORCHESTRATION
# Coordinates the complete streaming flow
# =============================================================================

class StreamOrchestrator:
    """
    Orchestrates the complete streaming flow.

    Responsibility:
        Coordinates all streaming components.
        Manages timeout tracking.
        Handles the message loop.
        Ensures proper cleanup.

    Flow:
        1. Subscribe to result channel
        2. Enqueue request
        3. Loop: receive messages → process → yield events
        4. Send heartbeats when idle
        5. Handle timeout
        6. Cleanup subscription
    """

    def __init__(
        self,
        enqueuer: RequestEnqueuer,
        subscriber: StreamSubscriber,
        streamer: EventStreamer,
        heartbeat: HeartbeatManager,
        config: StreamConfig,
    ):
        self._enqueuer = enqueuer
        self._subscriber = subscriber
        self._streamer = streamer
        self._heartbeat = heartbeat
        self._config = config

    async def stream(
        self,
        request_id: str,
        user_id: str,
        thread_id: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """
        Queue request and stream results via Redis Pub/Sub.

        Args:
            request_id: Unique request identifier
            user_id: User identifier
            thread_id: Thread identifier
            payload: Request payload

        Yields:
            SSE-formatted event strings

        Algorithm:
            1. Subscribe BEFORE enqueueing (avoid missing early events)
            2. Enqueue request to queue
            3. Poll Pub/Sub with dynamic timeout
            4. Process messages and yield events
            5. Send heartbeats when idle
            6. Stop on completion/error/timeout
        """
        try:
            # Step 1: Subscribe to result channel
            await self._subscriber.subscribe(request_id)

            # Step 2: Enqueue request
            await self._enqueuer.enqueue(request_id, user_id, thread_id, payload)

            logger.info(
                "Listening for stream response",
                stage="STREAM_WAIT",
                request_id=request_id,
                channel=self._subscriber.get_channel_name(request_id),
            )

            # Step 3: Stream loop
            async for event in self._message_loop(request_id):
                yield event

        except Exception as e:
            logger.error(
                "Queue stream failed",
                stage="STREAM_ERROR",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            yield self._streamer.format_exception_error(e)

        finally:
            # Step 4: Cleanup
            await self._subscriber.unsubscribe()
            logger.info(
                "Queue stream closed",
                stage="STREAM_CLOSE",
                request_id=request_id,
            )

    async def _message_loop(
        self,
        request_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Main message processing loop.

        Args:
            request_id: Request identifier for logging

        Yields:
            SSE-formatted event strings

        Loop Strategy:
            - Dynamic timeout for efficient polling
            - Heartbeats when idle
            - Timeout detection
            - Process messages as they arrive
        """
        start_time = time.time()

        while True:
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > self._config.timeout_seconds:
                logger.warning(
                    "Queue stream timeout",
                    stage="TIMEOUT",
                    request_id=request_id,
                    elapsed_seconds=elapsed,
                )
                yield self._streamer.format_timeout_error()
                break

            # Calculate dynamic poll timeout
            timeout = self._calculate_poll_timeout(elapsed)

            # Get message (blocks efficiently on server-side)
            message = await self._subscriber.get_message(timeout)

            if message:
                # Message received - process it
                self._heartbeat.record_activity()

                events, should_stop = await self._streamer.process_message(
                    message,
                    request_id,
                )

                # Yield all events from this message
                for event in events:
                    yield event

                if should_stop:
                    break

            else:
                # No message - check if heartbeat needed
                if self._heartbeat.should_send_ping():
                    yield self._heartbeat.get_ping_message()
                    self._heartbeat.record_activity()

                    logger.debug(
                        "Queue stream heartbeat sent",
                        stage="HEARTBEAT",
                        request_id=request_id,
                    )

    def _calculate_poll_timeout(self, elapsed: float) -> float:
        """
        Calculate optimal poll timeout for get_message().

        Balances responsiveness with efficiency:
            - Must wake for heartbeats (every 15s)
            - Must respect total timeout
            - Minimum 0.1s to avoid tight loops

        Args:
            elapsed: Seconds since stream started

        Returns:
            Timeout in seconds for next poll
        """
        time_until_ping = self._heartbeat.time_until_next_ping()
        time_until_timeout = self._config.timeout_seconds - elapsed

        # Use the smaller of the two constraints
        timeout = min(time_until_ping, time_until_timeout)

        # Enforce minimum to avoid tight loops
        return max(self._config.min_poll_interval_seconds, timeout)


# =============================================================================
# LAYER 6: PUBLIC API
# Clean interface for queue request handling
# =============================================================================

class QueueRequestHandler:
    """
    Handles queueing of streaming requests with distributed response streaming.

    Uses Redis Pub/Sub to receive streamed chunks from remote workers,
    enabling true streaming even during failover across distributed instances.

    Usage:
        handler = QueueRequestHandler()
        await handler.initialize()

        async for event in handler.queue_and_stream(user_id, thread_id, payload):
            # Send event to client
            yield event

    Architecture:
        Coordinates multiple layers to provide clean streaming interface:
        - RequestEnqueuer: Queue operations
        - StreamSubscriber: Pub/Sub subscription
        - EventStreamer: SSE formatting
        - HeartbeatManager: Keep-alive
        - StreamOrchestrator: Flow coordination
    """

    def __init__(self):
        """Initialize handler with configuration."""
        settings = get_settings()

        # Configuration
        self._enabled = getattr(settings, 'QUEUE_FAILOVER_ENABLED', True)
        self._config = StreamConfig(
            timeout_seconds=getattr(settings, 'QUEUE_FAILOVER_TIMEOUT_SECONDS', 30),
            ping_interval_seconds=15.0,
            min_poll_interval_seconds=0.1,
        )

        # Components (initialized in initialize())
        self._queue: MessageQueue | None = None
        self._redis: RedisClient | None = None
        self._orchestrator: StreamOrchestrator | None = None

        # State
        self._initialized = False

        logger.info(
            "Queue request handler configured",
            stage="INIT",
            enabled=self._enabled,
            timeout_seconds=self._config.timeout_seconds,
        )

    async def initialize(self) -> None:
        """
        Initialize handler and all dependencies.

        Must be called before queue_and_stream().
        """
        if self._initialized:
            return

        # Initialize queue
        self._queue = get_message_queue(
            topic="streaming_requests_failover",
            group_name="streaming_failover_consumers",
        )
        await self._queue.initialize()

        # Initialize Redis
        self._redis = get_redis_client()
        await self._redis.connect()

        # Build component layers
        settings = get_settings()
        metrics = get_metrics_collector()

        enqueuer = RequestEnqueuer(self._queue, metrics, settings)
        subscriber = StreamSubscriber(self._redis)
        streamer = EventStreamer()
        heartbeat = HeartbeatManager(self._config.ping_interval_seconds)

        self._orchestrator = StreamOrchestrator(
            enqueuer=enqueuer,
            subscriber=subscriber,
            streamer=streamer,
            heartbeat=heartbeat,
            config=self._config,
        )

        self._initialized = True

        logger.info("Queue request handler initialized", stage="INIT_COMPLETE")

    async def queue_and_stream(
        self,
        user_id: str,
        thread_id: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """
        Queue request and stream results via Redis Pub/Sub.

        Args:
            user_id: User identifier
            thread_id: Thread identifier
            payload: Request payload (query, model, provider, etc.)

        Yields:
            SSE-formatted event strings

        Raises:
            RuntimeError: If queue failover disabled or not initialized

        Flow:
            1. Generate unique request_id
            2. Subscribe to Redis result channel
            3. Enqueue request to message queue
            4. Stream events as they arrive
            5. Handle completion/error signals
            6. Cleanup subscription
        """
        if not self._enabled:
            raise RuntimeError("Queue failover is disabled")

        if not self._initialized:
            await self.initialize()

        # Generate unique request ID
        request_id = f"qr-{uuid.uuid4().hex[:12]}"

        # Stream through orchestrator
        async for event in self._orchestrator.stream(
            request_id=request_id,
            user_id=user_id,
            thread_id=thread_id,
            payload=payload,
        ):
            yield event


# =============================================================================
# GLOBAL INSTANCE MANAGEMENT (Singleton Pattern)
# =============================================================================

_handler_instance: QueueRequestHandler | None = None


def get_queue_request_handler() -> QueueRequestHandler:
    """
    Get global queue request handler instance.

    Returns:
        QueueRequestHandler: Singleton instance
    """
    global _handler_instance

    if _handler_instance is None:
        _handler_instance = QueueRequestHandler()

    return _handler_instance
