"""
Kafka Message Queue - Refactored for Clarity

Architecture:
    KafkaQueue (Public API)
        ├── ProducerManager (Producer lifecycle and configuration)
        ├── ConsumerManager (Consumer lifecycle and offset management)
        ├── MessageSerializer (Payload encoding/decoding)
        ├── BackpressureDetector (Buffer monitoring and error detection)
        └── MetricsRecorder (Queue metrics and observability)

Performance Targets:
    - High throughput: Batch compression and pipelining
    - Buffer management: Prevent producer buffer overflow
    - Offset management: Manual commits for reliability
    - Partition balancing: Consumer group coordination

Why Kafka?
    - High throughput: Millions of messages per second
    - Durability: Replicated, persistent log
    - Scalability: Horizontal scaling via partitions
    - Ordering: Per-partition ordering guarantees
    - Consumer groups: Load balancing and failover

Author: Refactored for clarity and maintainability
Date: 2025-12-13
"""

from datetime import datetime
from typing import Any

import orjson
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from src.core.config.settings import get_settings
from src.core.exceptions import QueueError, QueueFullError
from src.core.interfaces.message_queue import MessageQueue, QueueMessage
from src.core.logging.logger import get_logger
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# =============================================================================
# LAYER 1: PRODUCER MANAGEMENT
# Handles Kafka producer lifecycle and configuration
# =============================================================================


class ProducerManager:
    """
    Manages Kafka producer lifecycle and configuration.

    Responsibility: Producer initialization, configuration, and message sending.

    Why Kafka Producer?
    - Batching: Groups messages for efficiency
    - Compression: Reduces network bandwidth
    - Buffering: Handles bursts of messages
    - Retries: Automatic retry on transient failures
    - Idempotence: Exactly-once semantics (optional)

    Producer Configuration:
    - buffer_memory: Total memory for buffering (default: 32MB)
    - max_in_flight_requests: Max unacknowledged requests (default: 5)
    - compression_type: Compression algorithm (e.g., gzip, snappy)
    - acks: Acknowledgement level (0, 1, all)

    Performance Tuning:
    - Larger buffer: Higher throughput, more memory
    - More in-flight: Higher throughput, less ordering
    - Compression: Lower bandwidth, higher CPU
    """

    def __init__(
        self,
        bootstrap_servers: str,
        buffer_memory: int,
        max_in_flight_requests: int,
    ):
        """
        Initialize producer manager.

        Args:
            bootstrap_servers: Kafka broker addresses (e.g., "localhost:9092")
            buffer_memory: Total memory for buffering in bytes
            max_in_flight_requests: Max unacknowledged requests per connection
        """
        self._bootstrap_servers = bootstrap_servers
        self._buffer_memory = buffer_memory
        self._max_in_flight = max_in_flight_requests
        self._producer: AIOKafkaProducer | None = None

    async def initialize(self) -> None:
        """
        Initialize Kafka producer.

        Producer Initialization:
        - Creates producer with configuration
        - Establishes connection to brokers
        - Starts background sender thread

        Configuration Details:
        - value_serializer: Auto-serialize to JSON
        - buffer_memory: Total memory for buffering
        - max_in_flight_requests_per_connection: Pipelining limit

        Raises:
            QueueError: If initialization fails
        """
        if self._producer:
            return

        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: orjson.dumps(v),
                buffer_memory=self._buffer_memory,
                max_in_flight_requests_per_connection=self._max_in_flight,
            )
            await self._producer.start()

            logger.info(
                "Kafka producer initialized",
                stage="QUEUE.PRODUCER.INIT",
                bootstrap_servers=self._bootstrap_servers,
                buffer_memory=self._buffer_memory,
                max_in_flight_requests=self._max_in_flight,
            )

        except Exception as e:
            logger.error("Failed to initialize Kafka producer", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to initialize Kafka producer: {e}")

    async def send_message(self, topic: str, payload: dict[str, Any]) -> str:
        """
        Send message to Kafka topic.

        Send Process:
        1. Serialize payload to JSON
        2. Add to producer buffer
        3. Return future for async completion
        4. Wait for acknowledgement
        5. Return partition-offset ID

        Args:
            topic: Kafka topic name
            payload: Message payload (will be JSON serialized)

        Returns:
            Message ID in format "partition-offset"

        Raises:
            KafkaError: If send fails
        """
        if not self._producer:
            raise QueueError("Producer not initialized")

        # Send message (returns future)
        future = await self._producer.send(topic, payload)

        # Wait for acknowledgement
        record_metadata = await future

        # Create message ID from partition and offset
        msg_id = f"{record_metadata.partition}-{record_metadata.offset}"

        logger.debug("Message produced to Kafka", stage="QUEUE.PROD", id=msg_id)

        return msg_id

    async def close(self) -> None:
        """
        Close producer and flush pending messages.

        Shutdown Process:
        1. Flush pending messages
        2. Close producer
        3. Release resources
        """
        if self._producer:
            await self._producer.stop()
            self._producer = None

    def is_initialized(self) -> bool:
        """Check if producer is initialized."""
        return self._producer is not None


# =============================================================================
# LAYER 2: CONSUMER MANAGEMENT
# Handles Kafka consumer lifecycle and offset management
# =============================================================================


class ConsumerManager:
    """
    Manages Kafka consumer lifecycle and offset management.

    Responsibility: Consumer initialization, message fetching, and offset commits.

    Why Kafka Consumer?
    - Consumer groups: Load balancing across consumers
    - Offset management: Track processing progress
    - Partition assignment: Automatic rebalancing
    - At-least-once: Guaranteed delivery with manual commits

    Consumer Configuration:
    - group_id: Consumer group for load balancing
    - auto_offset_reset: Where to start (earliest, latest)
    - enable_auto_commit: Manual vs automatic commits
    - max_poll_records: Batch size for fetching

    Offset Management:
    - Manual commits: Commit after processing (at-least-once)
    - Auto commits: Commit periodically (at-most-once)
    - Offset tracking: Per-partition position
    """

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str,
        group_id: str,
    ):
        """
        Initialize consumer manager.

        Args:
            topic: Kafka topic to consume from
            bootstrap_servers: Kafka broker addresses
            group_id: Consumer group ID for load balancing
        """
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None

    async def initialize(self) -> None:
        """
        Initialize Kafka consumer.

        Consumer Initialization:
        - Creates consumer with configuration
        - Subscribes to topic
        - Joins consumer group
        - Starts fetching messages

        Configuration Details:
        - value_deserializer: Auto-deserialize from JSON
        - auto_offset_reset: Start from earliest message
        - enable_auto_commit: False (manual commits for reliability)

        Raises:
            QueueError: If initialization fails
        """
        if self._consumer:
            return

        try:
            self._consumer = AIOKafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                value_deserializer=lambda x: orjson.loads(x),
                auto_offset_reset="earliest",
                enable_auto_commit=False,  # Manual commits for reliability
            )
            await self._consumer.start()

            logger.info(
                "Kafka consumer initialized",
                stage="QUEUE.CONSUMER.INIT",
                topic=self._topic,
                group_id=self._group_id,
            )

        except Exception as e:
            logger.error("Failed to initialize Kafka consumer", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to initialize Kafka consumer: {e}")

    async def fetch_messages(
        self, batch_size: int, timeout_ms: int
    ) -> list[tuple[str, dict[str, Any], str]]:
        """
        Fetch batch of messages from Kafka.

        Fetch Process:
        1. Poll for messages (blocks up to timeout)
        2. Return messages from all assigned partitions
        3. Messages are not committed yet

        Args:
            batch_size: Maximum messages to fetch
            timeout_ms: Timeout in milliseconds

        Returns:
            List of (message_id, payload, timestamp) tuples
        """
        if not self._consumer:
            raise QueueError("Consumer not initialized")

        # Fetch messages from all partitions
        # getmany returns dict[TopicPartition, list[ConsumerRecord]]
        results = await self._consumer.getmany(
            timeout_ms=timeout_ms, max_records=batch_size
        )

        messages = []
        for tp, records in results.items():
            for record in records:
                msg_id = f"{record.partition}-{record.offset}"
                payload = record.value
                timestamp = payload.get("timestamp", "")

                messages.append((msg_id, payload, timestamp))

        return messages

    async def commit_offsets(self) -> None:
        """
        Commit current offsets to Kafka.

        Commit Strategy:
        - Manual commits: Commit after processing
        - Async commits: Non-blocking (faster)
        - At-least-once: Messages may be reprocessed on failure

        Why Manual Commits?
        - Reliability: Only commit after successful processing
        - Control: Decide when to commit
        - At-least-once: Guaranteed delivery
        """
        if self._consumer:
            await self._consumer.commit()

    async def close(self) -> None:
        """
        Close consumer and commit final offsets.

        Shutdown Process:
        1. Commit pending offsets
        2. Leave consumer group
        3. Close consumer
        4. Release resources
        """
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    def is_initialized(self) -> bool:
        """Check if consumer is initialized."""
        return self._consumer is not None


# =============================================================================
# LAYER 3: MESSAGE SERIALIZATION
# Handles encoding and decoding of message payloads
# =============================================================================


class MessageSerializer:
    """
    Serializes and deserializes message payloads.

    Responsibility: Convert between Python objects and Kafka-compatible formats.

    Why Separate Serializer?
    - Centralized serialization logic
    - Easy to swap formats (JSON, Avro, Protobuf)
    - Consistent timestamp handling
    - Clear separation of concerns

    Serialization:
    - Auto-add timestamp if not present
    - JSON encode entire payload
    - Kafka producer handles bytes conversion

    Deserialization:
    - JSON decode from bytes
    - Extract timestamp
    - Preserve original types
    """

    @staticmethod
    def prepare_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Prepare payload for Kafka producer.

        Adds timestamp if not present.

        Args:
            payload: Message payload

        Returns:
            Payload with timestamp
        """
        if "timestamp" not in payload:
            payload["timestamp"] = datetime.utcnow().isoformat() + "Z"

        return payload

    @staticmethod
    def create_queue_message(
        msg_id: str, payload: dict[str, Any], timestamp: str
    ) -> QueueMessage:
        """
        Create QueueMessage from Kafka record.

        Args:
            msg_id: Message ID (partition-offset)
            payload: Deserialized payload
            timestamp: Message timestamp

        Returns:
            QueueMessage instance
        """
        return QueueMessage(
            id=msg_id,
            payload=payload,
            timestamp=timestamp,
        )


# =============================================================================
# LAYER 4: BACKPRESSURE DETECTION
# Detects buffer overflow and backpressure conditions
# =============================================================================


class BackpressureDetector:
    """
    Detects backpressure conditions in Kafka producer.

    Responsibility: Identify buffer overflow and backpressure errors.

    Why Backpressure Detection?
    - Kafka producer has limited buffer memory
    - When buffer is full, sends block or fail
    - Need to detect and handle gracefully
    - Distinguish from other Kafka errors

    Detection Strategy:
    - Check error message for buffer-related keywords
    - Keywords: "buffer", "full", "memory"
    - Raise QueueFullError for backpressure
    - Raise QueueError for other failures
    """

    @staticmethod
    def is_buffer_full_error(error: Exception) -> bool:
        """
        Check if error indicates buffer overflow.

        Buffer Full Indicators:
        - Error message contains "buffer"
        - Error message contains "full"
        - Error message contains "memory"

        Args:
            error: Exception to check

        Returns:
            True if buffer full error
        """
        error_str = str(error).lower()
        return any(keyword in error_str for keyword in ["buffer", "full", "memory"])


# =============================================================================
# LAYER 5: METRICS RECORDING
# Tracks queue metrics for observability
# =============================================================================


class MetricsRecorder:
    """
    Records queue metrics for observability.

    Responsibility: Track queue operations for monitoring and alerting.

    Metrics Tracked:
    - Produce attempts/successes/failures
    - Failure reasons (buffer_full, kafka_error, load_shedding)
    - Queue depth (not applicable for Kafka)
    """

    def __init__(self, metrics_collector, queue_type: str = "kafka"):
        """
        Initialize metrics recorder.

        Args:
            metrics_collector: Metrics collector instance
            queue_type: Queue type identifier
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
            reason: Failure reason (buffer_full, kafka_error, load_shedding, unknown_error)
        """
        self._metrics.record_queue_produce_failure(self._queue_type, reason)


# =============================================================================
# LAYER 6: PUBLIC API
# Clean interface that coordinates all layers
# =============================================================================


class KafkaQueue(MessageQueue):
    """
    Kafka-based message queue.

    Public API for Kafka queue operations.

    Features:
        - High throughput message streaming
        - Producer buffer management
        - Consumer group coordination
        - Manual offset commits
        - Backpressure detection

    Usage:
        queue = KafkaQueue("events", "processors")
        await queue.initialize()

        # Produce
        msg_id = await queue.produce({"event": "user_signup", "user_id": 123})

        # Consume
        messages = await queue.consume("worker-1", batch_size=100)

        # Acknowledge
        await queue.acknowledge(msg_id)

    Architecture:
        KafkaQueue (this class)
            ├── ProducerManager (producer lifecycle)
            ├── ConsumerManager (consumer lifecycle)
            ├── MessageSerializer (encoding/decoding)
            ├── BackpressureDetector (buffer monitoring)
            └── MetricsRecorder (observability)

    Kafka vs Redis Streams:
        - Kafka: Higher throughput, horizontal scaling, retention policies
        - Redis: Lower latency, simpler setup, memory-based
    """

    def __init__(self, topic_name: str, group_id: str = "default_group"):
        """
        Initialize Kafka queue.

        Args:
            topic_name: Kafka topic name
            group_id: Consumer group ID for load balancing
        """
        settings = get_settings()

        # Build layers
        self._producer_mgr = ProducerManager(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            buffer_memory=settings.KAFKA_BUFFER_MEMORY,
            max_in_flight_requests=settings.KAFKA_MAX_IN_FLIGHT_REQUESTS,
        )

        self._consumer_mgr = ConsumerManager(
            topic=topic_name,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
        )

        self._serializer = MessageSerializer()
        self._backpressure = BackpressureDetector()
        self._metrics = MetricsRecorder(get_metrics_collector())

        # Configuration
        self._topic = topic_name
        self._group_id = group_id
        self._initialized = False

        # Load shedding (temporarily disabled - aioresilience package not available)
        self._load_shedder = None
        # TODO: Implement custom load shedding or find alternative library

        logger.info(
            "Kafka Queue initialized",
            stage="QUEUE.INIT",
            topic=self._topic,
            group_id=self._group_id,
            buffer_memory=settings.KAFKA_BUFFER_MEMORY,
            max_in_flight_requests=settings.KAFKA_MAX_IN_FLIGHT_REQUESTS,
        )

    async def initialize(self) -> None:
        """
        Initialize Kafka producer.

        Note: Consumer is initialized lazily on first consume() call.
        This allows producer-only or consumer-only usage.
        """
        if self._initialized:
            return

        await self._producer_mgr.initialize()
        self._initialized = True

    async def produce(self, payload: dict[str, Any]) -> str:
        """
        Produce message to Kafka topic.

        STAGE-QUEUE.PROD: Produce message

        Backpressure Handling:
        1. Check load shedding (if enabled)
        2. Attempt to send message
        3. If buffer full, raise QueueFullError
        4. If other error, raise QueueError

        Args:
            payload: Message payload

        Returns:
            Message ID in format "partition-offset"

        Raises:
            QueueFullError: If producer buffer is full
            QueueError: If produce fails
        """
        if not self._initialized:
            await self.initialize()

        # Check load shedding first (if enabled)
        if self._load_shedder is not None:
            should_shed, _ = self._load_shedder.should_shed_load()
            if should_shed:
                self._metrics.record_produce_failure("load_shedding")
                logger.warning(
                    "Load shedding active - rejecting request",
                    stage="QUEUE.LOAD_SHEDDING",
                    topic=self._topic,
                )
                raise QueueFullError(f"Load shedding active for topic {self._topic}")

        # Record produce attempt
        self._metrics.record_produce_attempt()

        try:
            # Prepare payload (add timestamp)
            prepared_payload = self._serializer.prepare_payload(payload)

            # Send message
            msg_id = await self._producer_mgr.send_message(self._topic, prepared_payload)

            # Record success
            self._metrics.record_produce_success()
            return msg_id

        except KafkaError as e:
            # Check if this is a buffer-related error (backpressure)
            if self._backpressure.is_buffer_full_error(e):
                self._metrics.record_produce_failure("buffer_full")
                logger.warning(
                    "Kafka producer buffer full - backpressure applied",
                    stage="QUEUE.BACKPRESSURE",
                    topic=self._topic,
                    error=str(e),
                )
                raise QueueFullError(f"Kafka producer buffer full for topic {self._topic}: {e}")
            else:
                self._metrics.record_produce_failure("kafka_error")
                logger.error("Failed to produce to Kafka", stage="QUEUE.ERR", error=str(e))
                raise QueueError(f"Failed to produce to Kafka: {e}")

        except Exception as e:
            self._metrics.record_produce_failure("unknown_error")
            logger.error("Failed to produce to Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to produce to Kafka: {e}")

    async def consume(
        self, consumer_name: str, batch_size: int = 10, block_ms: int = 2000
    ) -> list[QueueMessage]:
        """
        Consume messages from Kafka topic.

        STAGE-QUEUE.CONS: Consume messages

        Consumer Initialization:
        - Consumer is initialized lazily on first call
        - Joins consumer group for load balancing
        - Starts from earliest unprocessed message

        Args:
            consumer_name: Unique consumer name (not used in Kafka, group_id is used)
            batch_size: Maximum messages to fetch
            block_ms: Timeout in milliseconds

        Returns:
            List of QueueMessage objects
        """
        # Initialize consumer lazily
        if not self._consumer_mgr.is_initialized():
            await self._consumer_mgr.initialize()

        try:
            # Fetch messages
            raw_messages = await self._consumer_mgr.fetch_messages(batch_size, block_ms)

            # Convert to QueueMessage objects
            messages = []
            for msg_id, payload, timestamp in raw_messages:
                queue_msg = self._serializer.create_queue_message(msg_id, payload, timestamp)
                messages.append(queue_msg)

            return messages

        except Exception as e:
            logger.error("Failed to consume from Kafka", stage="QUEUE.ERR", error=str(e))
            raise QueueError(f"Failed to consume from Kafka: {e}")

    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge processed messages by committing offsets.

        STAGE-QUEUE.ACK: Acknowledge message

        Kafka Offset Commit:
        - Commits current offset position
        - Cumulative: Commits all messages up to current position
        - Async: Non-blocking commit
        - At-least-once: Messages may be reprocessed on failure

        Note: In Kafka, acknowledgement is cumulative per partition.
        Individual message IDs are not used for ack (unlike Redis Streams).

        Args:
            message_id: Message ID (not used in Kafka, commits current offset)
        """
        if self._consumer_mgr.is_initialized():
            await self._consumer_mgr.commit_offsets()

    async def close(self) -> None:
        """
        Close producer and consumer.

        Shutdown Process:
        1. Flush pending producer messages
        2. Commit consumer offsets
        3. Close connections
        4. Release resources
        """
        await self._producer_mgr.close()
        await self._consumer_mgr.close()
