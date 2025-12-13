"""
Redis Streams Message Queue - Refactored for Clarity

Architecture:
    RedisQueue (Public API)
        ├── StreamManager (Stream lifecycle and consumer groups)
        ├── BackpressureController (Queue depth monitoring and retry logic)
        ├── MessageSerializer (Payload encoding/decoding)
        ├── MetricsRecorder (Queue metrics and observability)
        └── ConsumerLoop (Continuous message consumption)

Performance Targets:
    - Queue depth monitoring: prevent overflow
    - Backpressure with exponential backoff: graceful degradation
    - Load shedding: protect system under extreme load
    - Batch consumption: efficient message processing

Why Redis Streams?
    - Persistent, ordered log of events
    - Consumer groups for load balancing
    - Acknowledgement mechanism (XACK) for reliability
    - Built-in blocking reads for efficiency

Author: Refactored for clarity and maintainability
Date: 2025-12-13
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import orjson
from redis.exceptions import RedisError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from src.core.config.settings import get_settings
from src.core.exceptions import QueueError, QueueFullError
from src.core.interfaces.message_queue import MessageQueue, QueueMessage
from src.core.logging.logger import get_logger
from src.infrastructure.cache.redis_client import RedisClient, get_redis_client
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# =============================================================================
# LAYER 1: STREAM MANAGEMENT
# Handles Redis Stream lifecycle and consumer group operations
# =============================================================================


class StreamManager:
    """
    Manages Redis Stream lifecycle and consumer groups.

    Responsibility: Stream creation, consumer group management, and initialization.

    Why Redis Streams?
    - Persistent log: Messages survive restarts
    - Consumer groups: Multiple workers can share workload
    - Acknowledgement: Ensure messages are processed
    - Blocking reads: Efficient waiting for new messages

    Consumer Group Pattern:
    - Stream: Ordered log of messages
    - Group: Logical set of consumers
    - Consumer: Individual worker instance
    - Pending: Messages delivered but not acknowledged
    """

    def __init__(self, stream_name: str, group_name: str, redis_client: RedisClient):
        """
        Initialize stream manager.

        Args:
            stream_name: Name of the Redis stream key
            group_name: Name of the consumer group
            redis_client: Redis client instance
        """
        self._stream_name = stream_name
        self._group_name = group_name
        self._redis = redis_client
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize consumer group for the stream.

        STAGE-QUEUE.1: Initialization

        Creates consumer group if it doesn't exist (idempotent operation).

        Consumer Group Creation:
        - XGROUP CREATE: Create group if doesn't exist
        - id="0": Start reading from beginning
        - mkstream=True: Create stream if doesn't exist
        - BUSYGROUP error: Group already exists (expected on restart)

        Raises:
            QueueError: If initialization fails
        """
        if self._initialized:
            return

        try:
            # MKSTREAM option creates the stream if it doesn't exist
            # id="0" means start reading from the beginning
            await self._redis.client.xgroup_create(
                self._stream_name,
                self._group_name,
                id="0",
                mkstream=True,
            )
            logger.info("Consumer group created", stage="QUEUE.1", group=self._group_name)
        except RedisError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, which is fine - this is idempotent
                logger.info(
                    "Consumer group already exists (OK)", stage="QUEUE.1", group=self._group_name
                )
            else:
                # Actual error - log and raise
                logger.error("Failed to create consumer group", stage="QUEUE.ERR", error=str(e))
                raise QueueError(f"Failed to create consumer group: {e}")

        self._initialized = True

    async def get_stream_length(self) -> int:
        """
        Get current stream length.

        Use Case: Monitor queue depth for backpressure

        Returns:
            Current number of messages in stream
        """
        return await self._redis.client.xlen(self._stream_name)

    async def add_message(
        self, message_data: dict[str, str], max_len: int
    ) -> str:
        """
        Add message to stream.

        XADD Command:
        - Adds message to stream
        - maxlen: Trim to approximate max length (memory management)
        - approximate=True: More efficient trimming

        Args:
            message_data: Message data (all values must be strings)
            max_len: Maximum stream length (approximate)

        Returns:
            Message ID (e.g., "1234567890123-0")
        """
        message_id = await self._redis.client.xadd(
            self._stream_name, message_data, maxlen=max_len, approximate=True
        )
        logger.debug("Message produced", stage="QUEUE.PROD", id=message_id)
        return message_id

    async def read_messages(
        self, consumer_name: str, batch_size: int, block_ms: int
    ) -> list[tuple[str, dict[str, str]]]:
        """
        Read messages from consumer group.

        XREADGROUP Command:
        - Reads messages for consumer group
        - ">" ID: Only new messages (not yet delivered)
        - block: Wait for messages (0 = infinite)
        - count: Maximum messages to return

        Args:
            consumer_name: Unique name for this consumer instance
            batch_size: Number of messages to fetch
            block_ms: Time to block waiting for messages (0 for infinite)

        Returns:
            List of (message_id, message_data) tuples
        """
        streams = {self._stream_name: ">"}

        response = await self._redis.client.xreadgroup(
            self._group_name, consumer_name, streams, count=batch_size, block=block_ms
        )

        messages = []
        if response:
            # response format: [[stream_name, [[id, {data}]]]]
            for stream, msg_list in response:
                for msg_id, msg_data in msg_list:
                    messages.append((msg_id, msg_data))

        return messages

    async def acknowledge_message(self, message_id: str) -> None:
        """
        Acknowledge a processed message.

        STAGE-QUEUE.ACK: Acknowledge message

        XACK Command:
        - Removes message from pending list
        - Confirms message was processed
        - Allows message to be trimmed eventually

        Args:
            message_id: The ID of the message to acknowledge
        """
        await self._redis.client.xack(self._stream_name, self._group_name, message_id)

    def get_stream_name(self) -> str:
        """Get stream name."""
        return self._stream_name

    def is_initialized(self) -> bool:
        """Check if stream manager is initialized."""
        return self._initialized


# =============================================================================
# LAYER 2: BACKPRESSURE CONTROL
# Monitors queue depth and applies backpressure when approaching capacity
# =============================================================================


class BackpressureController:
    """
    Controls backpressure and queue capacity management.

    Responsibility: Monitor queue depth and apply backpressure when needed.

    Why Backpressure?
    - Prevents queue overflow: Protects Redis memory
    - Graceful degradation: System slows down instead of failing
    - Fair queueing: Prevents producer from overwhelming consumers

    Strategy:
    1. Monitor queue depth
    2. If approaching capacity (>threshold%), warn
    3. If at capacity, retry with exponential backoff
    4. If still full after retries, reject request

    Configuration:
    - max_depth: Maximum queue size (e.g., 10000)
    - threshold: Warning threshold (e.g., 0.8 = 80%)
    - max_retries: Backpressure retries (e.g., 3)
    - base_delay: Initial retry delay (e.g., 0.1s)
    - max_delay: Maximum retry delay (e.g., 1.0s)
    """

    def __init__(
        self,
        max_depth: int,
        threshold: float,
        max_retries: int,
        base_delay: float,
        max_delay: float,
        stream_name: str,
    ):
        """
        Initialize backpressure controller.

        Args:
            max_depth: Maximum queue depth
            threshold: Backpressure threshold (0.0-1.0)
            max_retries: Maximum retry attempts
            base_delay: Initial retry delay in seconds
            max_delay: Maximum retry delay in seconds
            stream_name: Stream name for logging
        """
        self._max_depth = max_depth
        self._threshold = threshold
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._stream_name = stream_name

    def check_capacity(self, current_depth: int) -> tuple[bool, bool]:
        """
        Check queue capacity and determine backpressure action.

        Returns:
            (is_full, is_approaching_full) tuple
        """
        threshold_depth = int(self._threshold * self._max_depth)
        is_approaching_full = current_depth >= threshold_depth
        is_full = current_depth >= self._max_depth

        if is_full:
            logger.warning(
                "Queue at capacity, applying backpressure",
                stage="QUEUE.BACKPRESSURE",
                stream=self._stream_name,
                current_length=current_depth,
                max_length=self._max_depth,
                retries=self._max_retries,
            )
        elif is_approaching_full:
            logger.warning(
                "Queue approaching capacity",
                stage="QUEUE.WARNING",
                stream=self._stream_name,
                current_length=current_depth,
                max_length=self._max_depth,
                utilization=round(current_depth / self._max_depth * 100, 1),
            )

        return is_full, is_approaching_full

    def create_retry_handler(
        self,
        produce_fn: Callable[[], Awaitable[str]],
        check_depth_fn: Callable[[], Awaitable[int]],
    ):
        """
        Create retry handler with exponential backoff.

        Retry Strategy:
        - Use tenacity for automatic retry
        - Exponential backoff with jitter (prevents thundering herd)
        - Check queue depth before each retry
        - Log each retry attempt

        Args:
            produce_fn: Function to produce message
            check_depth_fn: Function to check current queue depth

        Returns:
            Async function that retries with backpressure
        """

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(
                initial=self._base_delay, max=self._max_delay
            ),
            retry=retry_if_exception_type(QueueFullError),
            before_sleep=lambda retry_state: logger.info(
                "Backpressure retry",
                stage="QUEUE.RETRY",
                attempt=retry_state.attempt_number,
                delay=round(retry_state.idle_for, 3),
                stream=self._stream_name,
            ),
        )
        async def _retry_with_backpressure():
            # Check stream length on each retry
            current_depth = await check_depth_fn()

            if current_depth >= self._max_depth:
                raise QueueFullError(
                    f"Queue full after {self._max_retries} retries: "
                    f"{current_depth}/{self._max_depth} messages in {self._stream_name}"
                )

            # Try to produce
            return await produce_fn()

        return _retry_with_backpressure


# =============================================================================
# LAYER 3: MESSAGE SERIALIZATION
# Handles encoding and decoding of message payloads
# =============================================================================


class MessageSerializer:
    """
    Serializes and deserializes message payloads.

    Responsibility: Convert between Python objects and Redis-compatible strings.

    Why Separate Serializer?
    - Centralized serialization logic
    - Easy to swap serialization formats
    - Consistent handling of complex types
    - Clear separation of concerns

    Serialization Strategy:
    - Primitives (str, int, float): Convert to string
    - Complex types (dict, list, bool): JSON encode
    - Auto-add timestamp if not present

    Deserialization Strategy:
    - Try to parse JSON if looks like JSON
    - Otherwise keep as string
    - Preserve original types where possible
    """

    @staticmethod
    def serialize(payload: dict[str, Any]) -> dict[str, str]:
        """
        Serialize payload for Redis Streams.

        Redis Streams Requirement:
        - All values must be strings
        - Complex types need JSON encoding

        Args:
            payload: Message payload

        Returns:
            Dict with all values as strings
        """
        # Add timestamp if not present
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Convert all values to strings
        # Complex types (dict, list, bool) are JSON encoded
        message_data = {}
        for k, v in payload.items():
            if isinstance(v, dict | list | bool):
                # JSON encode complex types
                message_data[k] = orjson.dumps(v).decode('utf-8')
            else:
                # Convert primitives to string
                message_data[k] = str(v)

        return message_data

    @staticmethod
    def deserialize(message_data: dict[str, str]) -> dict[str, Any]:
        """
        Deserialize message data from Redis Streams.

        Parsing Strategy:
        - If value looks like JSON (starts with { or [), try to parse
        - Otherwise keep as string
        - Gracefully handle parse errors

        Args:
            message_data: Raw message data from Redis

        Returns:
            Dict with parsed values
        """
        parsed_data = {}
        for k, v in message_data.items():
            try:
                # Try to parse JSON if it looks like it
                if v.startswith("{") or v.startswith("["):
                    parsed_data[k] = orjson.loads(v)
                else:
                    parsed_data[k] = v
            except (ValueError, AttributeError):
                # If parsing fails, keep as string
                parsed_data[k] = v

        return parsed_data


# =============================================================================
# LAYER 4: METRICS RECORDING
# Tracks queue metrics for observability
# =============================================================================


class MetricsRecorder:
    """
    Records queue metrics for observability.

    Responsibility: Track queue operations for monitoring and alerting.

    Why Separate Metrics?
    - Centralized metric recording
    - Easy to add new metrics
    - Decouples business logic from observability

    Metrics Tracked:
    - Produce attempts/successes/failures
    - Queue depth
    - Backpressure retries
    - Load shedding rejections
    """

    def __init__(self, metrics_collector, queue_type: str = "redis"):
        """
        Initialize metrics recorder.

        Args:
            metrics_collector: Metrics collector instance
            queue_type: Queue type identifier (e.g., "redis")
        """
        self._metrics = metrics_collector
        self._queue_type = queue_type

    def record_produce_attempt(self) -> None:
        """Record a produce attempt."""
        self._metrics.record_queue_produce_attempt(self._queue_type)

    def record_produce_success(self) -> None:
        """Record a successful produce."""
        self._metrics.record_queue_produce_success(self._queue_type)

    def record_produce_failure(self, reason: str) -> None:
        """
        Record a failed produce.

        Args:
            reason: Failure reason (e.g., "queue_full", "redis_error", "load_shedding")
        """
        self._metrics.record_queue_produce_failure(self._queue_type, reason)

    def record_queue_depth(self, stream_name: str, depth: int) -> None:
        """
        Record current queue depth.

        Args:
            stream_name: Stream name
            depth: Current queue depth
        """
        self._metrics.record_queue_depth(stream_name, depth)

    def record_backpressure_retry(self) -> None:
        """Record a backpressure retry attempt."""
        self._metrics.record_queue_backpressure_retry(self._queue_type)


# =============================================================================
# LAYER 5: CONSUMER LOOP
# Continuous message consumption with error handling
# =============================================================================


class ConsumerLoop:
    """
    Manages continuous message consumption loop.

    Responsibility: Consume, process, and acknowledge messages continuously.

    Why Separate Loop?
    - Isolates consumption logic
    - Easy to add retry/DLQ logic
    - Clear error handling strategy
    - Testable in isolation

    Algorithm:
    1. Consume batch of messages
    2. For each message:
        a. Process with handler
        b. Acknowledge if successful
        c. Log error if failed (DLQ candidate)
    3. Sleep if no messages (prevent tight loop)
    4. Retry on error with backoff
    """

    def __init__(
        self,
        stream_manager: StreamManager,
        message_serializer: MessageSerializer,
    ):
        """
        Initialize consumer loop.

        Args:
            stream_manager: Stream manager instance
            message_serializer: Message serializer instance
        """
        self._stream_mgr = stream_manager
        self._serializer = message_serializer

    async def run(
        self,
        consumer_name: str,
        handler: Callable[[QueueMessage], Awaitable[None]],
        batch_size: int = 10,
    ) -> None:
        """
        Start continuous consumer loop.

        Loop Behavior:
        - Runs indefinitely until stopped
        - Blocks waiting for messages (efficient)
        - Processes messages in batches
        - Acknowledges successful processing
        - Logs errors (DLQ candidates)
        - Backs off on errors

        Args:
            consumer_name: Unique consumer name
            handler: Async function to process each message
            batch_size: Number of messages to consume per batch
        """
        logger.info("Starting consumer loop", stage="QUEUE.LOOP", consumer=consumer_name)

        while True:
            try:
                # Consume batch of messages
                raw_messages = await self._stream_mgr.read_messages(
                    consumer_name, batch_size, block_ms=2000
                )

                # Process each message
                for msg_id, msg_data in raw_messages:
                    try:
                        # Deserialize message
                        parsed_data = self._serializer.deserialize(msg_data)

                        # Create QueueMessage
                        queue_msg = QueueMessage(
                            id=msg_id,
                            payload=parsed_data,
                            timestamp=parsed_data.get("timestamp", ""),
                        )

                        # Process message with handler
                        await handler(queue_msg)

                        # Acknowledge success
                        await self._stream_mgr.acknowledge_message(msg_id)

                    except Exception as e:
                        logger.error(
                            "Error processing message",
                            stage="QUEUE.PROC_ERR",
                            id=msg_id,
                            error=str(e),
                        )
                        # TODO: Implement DLQ or retry logic here

                # Small sleep if no messages to prevent tight loop
                if not raw_messages:
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("Consumer loop error", stage="QUEUE.LOOP_ERR", error=str(e))
                await asyncio.sleep(5)  # Backoff on error


# =============================================================================
# LAYER 6: PUBLIC API
# Clean interface that coordinates all layers
# =============================================================================


class RedisQueue(MessageQueue):
    """
    Redis Streams-based message queue.

    Public API for queue operations.

    Features:
        - Producer-consumer pattern
        - Backpressure control
        - Consumer groups for load balancing
        - Message acknowledgement
        - Continuous consumer loop

    Usage:
        queue = RedisQueue("task_queue", "workers")
        await queue.initialize()

        # Produce
        msg_id = await queue.produce({"task": "send_email", "user_id": 123})

        # Consume
        messages = await queue.consume("worker-1", batch_size=10)

        # Acknowledge
        await queue.acknowledge(msg_id)

        # Consumer loop
        async def handler(msg):
            print(f"Processing: {msg.payload}")

        await queue.start_consumer_loop("worker-1", handler)

    Architecture:
        RedisQueue (this class)
            ├── StreamManager (stream lifecycle)
            ├── BackpressureController (capacity management)
            ├── MessageSerializer (encoding/decoding)
            ├── MetricsRecorder (observability)
            └── ConsumerLoop (consumption)

    STAGE-QUEUE: Queue operations
    """

    def __init__(self, stream_name: str, group_name: str = "default_group"):
        """
        Initialize Redis Queue.

        Args:
            stream_name: Name of the Redis stream key
            group_name: Name of the consumer group
        """
        settings = get_settings()

        # Build layers
        self._redis: RedisClient | None = None
        self._stream_mgr: StreamManager | None = None
        self._backpressure: BackpressureController | None = None
        self._serializer = MessageSerializer()
        self._metrics = MetricsRecorder(get_metrics_collector())
        self._consumer_loop: ConsumerLoop | None = None

        # Configuration
        self._stream_name = f"queue:{stream_name}"
        self._group_name = group_name
        self._max_depth = settings.QUEUE_MAX_DEPTH

        # Load shedding (temporarily disabled - aioresilience package not available)
        self._load_shedder = None
        # TODO: Implement custom load shedding or find alternative library

        logger.info(
            "Redis Queue initialized",
            stage="QUEUE.0",
            stream=self._stream_name,
            group=self._group_name,
            max_depth=self._max_depth,
            backpressure_threshold=settings.QUEUE_BACKPRESSURE_THRESHOLD,
            load_shedding_enabled=settings.QUEUE_LOAD_SHEDDING_ENABLED,
        )

    async def initialize(self) -> None:
        """
        Initialize Redis connection and consumer group.

        STAGE-QUEUE.1: Initialization
        """
        if self._stream_mgr and self._stream_mgr.is_initialized():
            return

        # Initialize Redis client
        self._redis = get_redis_client()
        await self._redis.connect()

        # Initialize layers
        settings = get_settings()

        self._stream_mgr = StreamManager(
            self._stream_name, self._group_name, self._redis
        )
        await self._stream_mgr.initialize()

        self._backpressure = BackpressureController(
            max_depth=self._max_depth,
            threshold=settings.QUEUE_BACKPRESSURE_THRESHOLD,
            max_retries=settings.QUEUE_BACKPRESSURE_MAX_RETRIES,
            base_delay=settings.QUEUE_BACKPRESSURE_BASE_DELAY,
            max_delay=settings.QUEUE_BACKPRESSURE_MAX_DELAY,
            stream_name=self._stream_name,
        )

        self._consumer_loop = ConsumerLoop(self._stream_mgr, self._serializer)

    async def produce(self, payload: dict[str, Any], max_len: int | None = None) -> str:
        """
        Add a message to the queue with backpressure handling.

        STAGE-QUEUE.PROD: Produce message

        Backpressure Strategy:
        1. Check load shedding (if enabled)
        2. Check current queue depth
        3. If approaching capacity, warn
        4. If at capacity, retry with exponential backoff
        5. If still full, reject request

        Args:
            payload: Dictionary data to send
            max_len: Maximum length of the stream (approximate trimming)
                If None, uses configured max_depth

        Returns:
            Message ID

        Raises:
            QueueFullError: If queue is full after retries
            QueueError: If produce fails
        """
        if not self._stream_mgr or not self._stream_mgr.is_initialized():
            await self.initialize()

        # Use configured max_len if not provided
        if max_len is None:
            max_len = self._max_depth

        # Record produce attempt
        self._metrics.record_produce_attempt()

        try:
            # Check current stream length
            stream_length = await self._stream_mgr.get_stream_length()

            # Record current queue depth
            self._metrics.record_queue_depth(self._stream_name, stream_length)

            # Check load shedding first (if enabled)
            if self._load_shedder is not None:
                should_shed, _ = self._load_shedder.should_shed_load()
                if should_shed:
                    self._metrics.record_produce_failure("load_shedding")
                    logger.warning(
                        "Load shedding active - rejecting request",
                        stage="QUEUE.LOAD_SHEDDING",
                        stream=self._stream_name,
                    )
                    raise QueueFullError(f"Load shedding active for queue {self._stream_name}")

            # Check backpressure
            is_full, is_approaching_full = self._backpressure.check_capacity(stream_length)

            if is_full:
                # Queue is full - apply backpressure with retries
                message_id = await self._produce_with_backpressure(payload, max_len)
                self._metrics.record_produce_success()
                return message_id

            # Normal produce operation
            message_id = await self._produce_message(payload, max_len)
            self._metrics.record_produce_success()
            return message_id

        except RedisError as e:
            self._metrics.record_produce_failure("redis_error")
            logger.error("Failed to produce message", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to produce message: {e}")
        except QueueFullError:
            # Re-raise QueueFullError (already logged and metrics recorded)
            raise

    async def _produce_with_backpressure(self, payload: dict[str, Any], max_len: int) -> str:
        """
        Produce message with backpressure retry logic.

        Uses tenacity for automatic retry with exponential backoff.

        Args:
            payload: Message payload
            max_len: Maximum stream length

        Returns:
            Message ID

        Raises:
            QueueFullError: When all retries are exhausted
        """
        # Create retry handler
        retry_handler = self._backpressure.create_retry_handler(
            produce_fn=lambda: self._produce_message(payload, max_len),
            check_depth_fn=self._stream_mgr.get_stream_length,
        )

        try:
            return await retry_handler()
        except QueueFullError:
            self._metrics.record_produce_failure("queue_full")
            raise

    async def _produce_message(self, payload: dict[str, Any], max_len: int) -> str:
        """
        Internal method to produce a single message.

        Steps:
        1. Serialize payload to Redis-compatible format
        2. Add to stream with XADD
        3. Return message ID

        Args:
            payload: Message payload
            max_len: Maximum stream length

        Returns:
            Message ID
        """
        # Serialize payload
        message_data = self._serializer.serialize(payload)

        # Add to stream
        message_id = await self._stream_mgr.add_message(message_data, max_len)

        return message_id

    async def consume(
        self, consumer_name: str, batch_size: int = 10, block_ms: int = 2000
    ) -> list[QueueMessage]:
        """
        Consume messages from the queue.

        STAGE-QUEUE.CONS: Consume messages

        Args:
            consumer_name: Unique name for this consumer instance
            batch_size: Number of messages to fetch
            block_ms: Time to block waiting for messages (0 for infinite)

        Returns:
            List of QueueMessage objects
        """
        if not self._stream_mgr or not self._stream_mgr.is_initialized():
            await self.initialize()

        try:
            # Read messages from stream
            raw_messages = await self._stream_mgr.read_messages(
                consumer_name, batch_size, block_ms
            )

            # Deserialize and convert to QueueMessage
            messages = []
            for msg_id, msg_data in raw_messages:
                parsed_data = self._serializer.deserialize(msg_data)

                messages.append(
                    QueueMessage(
                        id=msg_id,
                        payload=parsed_data,
                        timestamp=parsed_data.get("timestamp", ""),
                    )
                )

            return messages

        except RedisError as e:
            logger.error("Failed to consume messages", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to consume messages: {e}")

    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge a processed message.

        STAGE-QUEUE.ACK: Acknowledge message

        Args:
            message_id: The ID of the message to acknowledge
        """
        if not self._stream_mgr or not self._stream_mgr.is_initialized():
            await self.initialize()

        try:
            await self._stream_mgr.acknowledge_message(message_id)
        except RedisError as e:
            logger.error("Failed to acknowledge message", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to acknowledge message: {e}")

    async def start_consumer_loop(
        self,
        consumer_name: str,
        handler: Callable[[QueueMessage], Awaitable[None]],
        batch_size: int = 10,
    ) -> None:
        """
        Start a continuous consumer loop.

        Runs indefinitely, consuming and processing messages.

        Args:
            consumer_name: Unique consumer name
            handler: Async function to process each message
            batch_size: Batch size for consumption
        """
        if not self._consumer_loop:
            await self.initialize()

        await self._consumer_loop.run(consumer_name, handler, batch_size)

    async def close(self) -> None:
        """Close the connection (no-op for Redis as client is shared)."""
        pass
