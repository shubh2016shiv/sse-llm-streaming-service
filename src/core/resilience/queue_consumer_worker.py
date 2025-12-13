"""
Queue Consumer Worker - Distributed Streaming Publisher

Processes streaming requests from queue and publishes results via Redis Pub/Sub.

Architecture:
    QueueConsumerWorker (Public API)
        ├── MessageProcessor (Business logic for request processing)
        ├── StreamPublisher (Redis Pub/Sub publishing)
        ├── ConnectionManager (Connection pool coordination)
        └── RetryStrategy (Retry/backoff logic)

Flow:
    1. Consume message from queue
    2. Acquire connection from pool
    3. Stream LLM response chunk-by-chunk
    4. Publish each chunk to Redis channel: queue:results:{request_id}
    5. Publish SIGNAL:DONE when complete
    6. Release connection

This enables real-time streaming to any instance subscribing to the channel.
"""

import asyncio
import socket
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from src.core.config.settings import get_settings
from src.core.exceptions.connection_pool import (
    ConnectionPoolExhaustedError,
    UserConnectionLimitError,
)
from src.core.interfaces.message_queue import QueueMessage
from src.core.logging.logger import get_logger
from src.core.resilience.connection_pool_manager import get_connection_pool_manager
from src.core.resilience.queue_request_handler import QueuedStreamingRequest
from src.infrastructure.cache.redis_client import RedisClient, get_redis_client
from src.infrastructure.message_queue.base import MessageQueue
from src.infrastructure.message_queue.factory import get_message_queue
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

class SignalType(str, Enum):
    """
    Signal types for stream lifecycle events.

    These signals are published to Redis channels to indicate
    stream state transitions to all subscribers.
    """
    DONE = "SIGNAL:DONE"
    ERROR = "SIGNAL:ERROR"
    HEARTBEAT = "SIGNAL:HEARTBEAT"


@dataclass
class WorkerConfig:
    """
    Worker configuration parameters.

    Attributes:
        max_retries: Maximum retry attempts for failed requests
        timeout_seconds: Request timeout threshold (age-based)
        base_delay_ms: Base delay for exponential backoff
        max_backoff_ms: Maximum backoff delay cap
        batch_size: Number of messages to consume per batch
        poll_interval_ms: Queue polling interval when no messages
        error_backoff_seconds: Backoff after consumer loop errors
        shutdown_timeout_seconds: Graceful shutdown timeout
    """
    max_retries: int = 5
    timeout_seconds: int = 30
    base_delay_ms: int = 100
    max_backoff_ms: int = 5000
    batch_size: int = 5
    poll_interval_ms: int = 2000
    error_backoff_seconds: int = 5
    shutdown_timeout_seconds: float = 5.0


# =============================================================================
# PROTOCOLS & INTERFACES
# Define contracts for dependency injection and testing
# =============================================================================

class StreamOrchestrator(Protocol):
    """
    Protocol for LLM stream orchestrator.

    Defines the interface for streaming LLM responses.
    Enables dependency injection and testing with mock orchestrators.
    """

    async def stream(
        self,
        query: str,
        model: str,
        provider: str,
        user_id: str,
    ) -> AsyncIterator[str]:
        """
        Stream LLM response events.

        Args:
            query: User query
            model: LLM model name
            provider: LLM provider name
            user_id: User identifier

        Yields:
            SSE-formatted event strings
        """
        ...


class ConnectionPoolManager(Protocol):
    """
    Protocol for connection pool manager.

    Defines the interface for acquiring and releasing connections.
    Enables dependency injection and testing.
    """

    async def acquire_connection(self, user_id: str, thread_id: str) -> None:
        """Acquire connection from pool."""
        ...

    async def release_connection(self, user_id: str, thread_id: str) -> None:
        """Release connection back to pool."""
        ...


# =============================================================================
# LAYER 1: STREAMING & PUBLISHING
# Handles interaction with LLM orchestrator and Redis Pub/Sub
# =============================================================================

class StreamPublisher:
    """
    Publishes streaming events to Redis Pub/Sub channel.

    Responsibility:
        Handles all Redis publishing for streaming events.
        Isolates Pub/Sub logic from business logic.

    Channel Format:
        queue:results:{request_id}

    Message Types:
        - SSE chunks: "data: {json}\n\n"
        - Completion: "SIGNAL:DONE"
        - Error: "SIGNAL:ERROR:{message}"
        - Heartbeat: "SIGNAL:HEARTBEAT"
    """

    RESULT_CHANNEL_PREFIX = "queue:results:"

    def __init__(self, redis_client: RedisClient):
        """
        Initialize stream publisher.

        Args:
            redis_client: Redis client for Pub/Sub operations
        """
        self._redis = redis_client

    def get_channel_name(self, request_id: str) -> str:
        """
        Generate Redis channel name for request.

        Args:
            request_id: Unique request identifier

        Returns:
            Channel name in format: queue:results:{request_id}
        """
        return f"{self.RESULT_CHANNEL_PREFIX}{request_id}"

    async def publish_chunk(self, request_id: str, chunk: str) -> None:
        """
        Publish single chunk to request channel.

        Args:
            request_id: Unique request identifier
            chunk: SSE-formatted event string

        Raises:
            Exception: If Redis publish fails
        """
        channel = self.get_channel_name(request_id)
        try:
            await self._redis.publish(channel, chunk)
        except Exception as e:
            logger.error(
                "Failed to publish chunk",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def publish_signal(
        self,
        request_id: str,
        signal: SignalType,
        message: str = "",
    ) -> None:
        """
        Publish lifecycle signal to request channel.

        Args:
            request_id: Unique request identifier
            signal: Signal type (DONE, ERROR, HEARTBEAT)
            message: Optional message for ERROR signals

        Raises:
            Exception: If Redis publish fails
        """
        channel = self.get_channel_name(request_id)

        # Format signal message
        if signal == SignalType.ERROR and message:
            signal_msg = f"{signal.value}:{message}"
        else:
            signal_msg = signal.value

        try:
            await self._redis.publish(channel, signal_msg)
        except Exception as e:
            logger.error(
                "Failed to publish signal",
                request_id=request_id,
                signal=signal.value,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def publish_completion(self, request_id: str) -> None:
        """
        Publish completion signal to request channel.

        Args:
            request_id: Unique request identifier
        """
        await self.publish_signal(request_id, SignalType.DONE)

    async def publish_error(self, request_id: str, error: str) -> None:
        """
        Publish error signal to request channel.

        Args:
            request_id: Unique request identifier
            error: Error message
        """
        await self.publish_signal(request_id, SignalType.ERROR, error)


class StreamExecutor:
    """
    Executes streaming request and yields chunks.

    Responsibility:
        Interfaces with LLM orchestrator to execute streaming requests.
        Separates orchestrator interaction from publishing logic.

    Design Pattern:
        Uses factory pattern for orchestrator creation to enable
        dependency injection and testing with mock orchestrators.
    """

    def __init__(self, orchestrator_factory: Callable[[], StreamOrchestrator] | None = None):
        """
        Initialize stream executor.

        Args:
            orchestrator_factory: Factory function to get orchestrator.
                                 If None, uses default from stream_orchestrator module.
        """
        self._orchestrator_factory = orchestrator_factory

    def _get_orchestrator(self) -> StreamOrchestrator:
        """
        Get orchestrator instance.

        Uses lazy initialization to avoid circular dependencies.

        Returns:
            Stream orchestrator instance
        """
        if self._orchestrator_factory:
            return self._orchestrator_factory()

        # Lazy import to avoid circular dependencies
        from src.llm_stream.services.stream_orchestrator import get_stream_orchestrator
        return get_stream_orchestrator()

    async def execute_stream(
        self,
        query: str,
        model: str,
        provider: str,
        user_id: str,
    ) -> AsyncIterator[str]:
        """
        Execute streaming request and yield SSE-formatted chunks.

        Args:
            query: User query
            model: LLM model name
            provider: LLM provider name
            user_id: User identifier

        Yields:
            SSE-formatted event strings

        Raises:
            Exception: If streaming fails
        """
        orchestrator = self._get_orchestrator()

        # Stream events from orchestrator
        async for event in orchestrator.stream(
            query=query,
            model=model,
            provider=provider,
            user_id=user_id,
        ):
            yield event


# =============================================================================
# LAYER 2: CONNECTION MANAGEMENT
# Handles connection pool acquisition and release with context managers
# =============================================================================

@dataclass
class ProcessingContext:
    """
    Context for processing a single request.

    Tracks state throughout the request processing lifecycle.

    Attributes:
        request: Queued streaming request
        message: Original queue message
        connection_acquired: Whether connection was acquired from pool
        start_time: Processing start timestamp
        metadata: Additional context metadata
    """
    request: QueuedStreamingRequest
    message: QueueMessage
    connection_acquired: bool = False
    start_time: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed processing time in seconds."""
        return time.time() - self.start_time

    @property
    def request_age_seconds(self) -> float:
        """Get request age since enqueue in seconds."""
        return time.time() - self.request.enqueue_time


class ConnectionManager:
    """
    Manages connection pool operations for request processing.

    Responsibility:
        Acquires and releases connections from pool.
        Ensures connections are properly released even on errors.
        Provides context manager for automatic cleanup.

    Design Pattern:
        Implements context manager protocol for automatic resource cleanup.
        This ensures connections are always released, even on exceptions.
    """

    def __init__(self, pool_manager: ConnectionPoolManager):
        """
        Initialize connection manager.

        Args:
            pool_manager: Connection pool manager instance
        """
        self._pool_manager = pool_manager

    @asynccontextmanager
    async def acquire_connection(self, user_id: str, thread_id: str):
        """
        Acquire connection from pool with automatic cleanup.

        Context manager ensures connection is released even on exceptions.

        Args:
            user_id: User identifier
            thread_id: Thread identifier

        Yields:
            None (connection is managed internally)

        Raises:
            UserConnectionLimitError: User exceeded connection limit
            ConnectionPoolExhaustedError: Pool exhausted

        Example:
            async with connection_mgr.acquire_connection(user_id, thread_id):
                # Connection acquired
                await process_request()
                # Connection automatically released on exit
        """
        try:
            # Acquire connection
            await self._pool_manager.acquire_connection(user_id, thread_id)
            logger.debug(
                "Connection acquired",
                user_id=user_id,
                thread_id=thread_id,
            )

            # Yield control to caller
            yield

        finally:
            # Always release connection, even on exceptions
            try:
                await self._pool_manager.release_connection(user_id, thread_id)
                logger.debug(
                    "Connection released",
                    user_id=user_id,
                    thread_id=thread_id,
                )
            except Exception as e:
                # Log but don't raise - we're in cleanup
                logger.error(
                    "Failed to release connection",
                    user_id=user_id,
                    thread_id=thread_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )


# =============================================================================
# LAYER 3: RETRY STRATEGY
# Implements exponential backoff retry logic
# =============================================================================

class RetryStrategy:
    """
    Implements retry logic with exponential backoff.

    Responsibility:
        Determines if request should be retried.
        Calculates backoff delays.
        Re-queues failed requests.

    Algorithm:
        - Exponential backoff: delay = base_delay * 2^retry_count
        - Max delay capped at max_backoff_ms (default: 5000ms)
        - Max retries configurable (default: 5)

    Design Rationale:
        Exponential backoff prevents thundering herd when services recover.
        Capped max delay prevents indefinite waiting.
        Max retries prevent infinite retry loops.
    """

    def __init__(
        self,
        queue: MessageQueue,
        publisher: StreamPublisher,
        config: WorkerConfig,
    ):
        """
        Initialize retry strategy.

        Args:
            queue: Message queue for re-queuing requests
            publisher: Stream publisher for error notifications
            config: Worker configuration
        """
        self._queue = queue
        self._publisher = publisher
        self._config = config

    def should_retry(self, request: QueuedStreamingRequest) -> bool:
        """
        Check if request should be retried.

        Args:
            request: Queued request

        Returns:
            True if retry count below max_retries
        """
        return request.retry_count < self._config.max_retries

    def calculate_backoff_delay(self, retry_count: int) -> float:
        """
        Calculate exponential backoff delay in seconds.

        Formula: delay = min(base_delay * 2^retry_count, max_backoff)

        Args:
            retry_count: Current retry attempt number (0-indexed)

        Returns:
            Delay in seconds

        Example:
            base_delay=100ms, max_backoff=5000ms
            retry_count=0: 100ms
            retry_count=1: 200ms
            retry_count=2: 400ms
            retry_count=3: 800ms
            retry_count=4: 1600ms
            retry_count=5: 3200ms
            retry_count=6: 5000ms (capped)
        """
        delay_ms = min(
            self._config.base_delay_ms * (2 ** retry_count),
            self._config.max_backoff_ms
        )
        return delay_ms / 1000.0

    async def handle_retry(
        self,
        message: QueueMessage,
        request: QueuedStreamingRequest,
        error: str,
    ) -> None:
        """
        Handle retry for failed request.

        If max retries exceeded, publishes error and acknowledges message.
        Otherwise, applies backoff and re-queues request.

        Args:
            message: Original queue message
            request: Queued request to retry
            error: Error message from failure
        """
        if not self.should_retry(request):
            # Max retries exceeded - give up
            logger.warning(
                "Max retries exceeded, giving up",
                request_id=request.request_id,
                retries=request.retry_count,
                error=error,
            )

            await self._publisher.publish_error(
                request.request_id,
                f"Max retries exceeded: {error}"
            )
            await self._queue.acknowledge(message.id)
            return

        # Calculate backoff delay
        delay = self.calculate_backoff_delay(request.retry_count)

        logger.info(
            "Retrying request with backoff",
            request_id=request.request_id,
            retry_count=request.retry_count,
            delay_seconds=delay,
            error=error,
        )

        # Apply backoff
        await asyncio.sleep(delay)

        # Re-queue with incremented retry count
        request.retry_count += 1
        await self._queue.produce(request.to_dict())

        # Acknowledge original message
        await self._queue.acknowledge(message.id)


# =============================================================================
# LAYER 4: MESSAGE PROCESSING
# Orchestrates request processing through the pipeline
# =============================================================================

class MessageProcessor:
    """
    Processes individual queue messages through the streaming pipeline.

    Responsibility:
        Orchestrates the complete request processing flow:
        - Timeout validation
        - Connection acquisition (via context manager)
        - Stream execution
        - Chunk publishing
        - Error handling
        - Retry coordination

    This is the core business logic layer that coordinates all other components.

    Design Pattern:
        Uses dependency injection for all components to enable testing.
        Uses context managers for automatic resource cleanup.
        Separates concerns: each component has single responsibility.
    """

    def __init__(
        self,
        executor: StreamExecutor,
        publisher: StreamPublisher,
        connection_mgr: ConnectionManager,
        retry_strategy: RetryStrategy,
        queue: MessageQueue,
        config: WorkerConfig,
        metrics,
    ):
        """
        Initialize message processor.

        Args:
            executor: Stream executor for LLM streaming
            publisher: Stream publisher for Redis Pub/Sub
            connection_mgr: Connection manager for pool operations
            retry_strategy: Retry strategy for failed requests
            queue: Message queue for acknowledgments
            config: Worker configuration
            metrics: Metrics collector for observability
        """
        self._executor = executor
        self._publisher = publisher
        self._connection_mgr = connection_mgr
        self._retry_strategy = retry_strategy
        self._queue = queue
        self._config = config
        self._metrics = metrics

    async def process(self, message: QueueMessage) -> None:
        """
        Process single queue message.

        Orchestrates the complete request processing pipeline:
        1. Parse and validate request
        2. Check timeout
        3. Acquire connection
        4. Execute stream
        5. Publish chunks
        6. Handle errors and retries
        7. Release connection

        Args:
            message: Queue message containing streaming request
        """
        # Parse request from message
        try:
            request = QueuedStreamingRequest.from_dict(message.payload)
        except Exception as e:
            logger.error(
                "Failed to parse queue message",
                message_id=message.id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Acknowledge invalid message to prevent poison pill
            await self._queue.acknowledge(message.id)
            return

        # Create processing context
        ctx = ProcessingContext(request=request, message=message)

        # Validate timeout
        if self._is_timed_out(ctx):
            logger.warning(
                "Request timed out, skipping",
                request_id=ctx.request.request_id,
                age_seconds=ctx.request_age_seconds,
                timeout_seconds=self._config.timeout_seconds,
            )
            await self._queue.acknowledge(message.id)
            return

        # Process with error handling
        try:
            await self._process_with_connection(ctx)

            # Success - acknowledge message
            await self._queue.acknowledge(message.id)
            self._metrics.record_queue_consume_success("failover")

            logger.info(
                "Request processed successfully",
                request_id=ctx.request.request_id,
                elapsed_seconds=ctx.elapsed_seconds,
            )

        except (UserConnectionLimitError, ConnectionPoolExhaustedError) as e:
            # Connection pool exhausted - retry with backoff
            logger.warning(
                "Connection pool exhausted, will retry",
                request_id=ctx.request.request_id,
                error=str(e),
                error_type=type(e).__name__,
            )

            await self._retry_strategy.handle_retry(
                message,
                ctx.request,
                f"Connection pool exhausted: {str(e)}"
            )

        except Exception as e:
            # Unexpected error - publish error and acknowledge to prevent poison pill
            logger.error(
                "Unexpected error processing request",
                request_id=ctx.request.request_id,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

            await self._publisher.publish_error(
                ctx.request.request_id,
                f"Processing error: {str(e)}"
            )
            await self._queue.acknowledge(message.id)

    def _is_timed_out(self, ctx: ProcessingContext) -> bool:
        """
        Check if request has exceeded timeout.

        Args:
            ctx: Processing context

        Returns:
            True if request age exceeds configured timeout
        """
        return ctx.request_age_seconds > self._config.timeout_seconds

    async def _process_with_connection(self, ctx: ProcessingContext) -> None:
        """
        Process request with connection acquisition.

        Uses context manager to ensure connection is released.

        Args:
            ctx: Processing context

        Raises:
            UserConnectionLimitError: User exceeded connection limit
            ConnectionPoolExhaustedError: Pool exhausted
            Exception: If streaming or publishing fails
        """
        # Acquire connection with automatic cleanup
        async with self._connection_mgr.acquire_connection(
            ctx.request.user_id,
            ctx.request.thread_id,
        ):
            ctx.connection_acquired = True

            # Process stream
            await self._process_stream(ctx)

    async def _process_stream(self, ctx: ProcessingContext) -> None:
        """
        Execute stream and publish chunks to Redis.

        Args:
            ctx: Processing context

        Raises:
            Exception: If streaming or publishing fails
        """
        logger.info(
            "Processing queued streaming request",
            request_id=ctx.request.request_id,
            user_id=ctx.request.user_id,
            retry_count=ctx.request.retry_count,
        )

        # Extract request parameters
        payload = ctx.request.payload
        query = payload.get("query", "")
        model = payload.get("model", "gpt-3.5-turbo")
        provider = payload.get("provider", "fake")

        # Stream and publish chunks
        chunk_count = 0
        async for event in self._executor.execute_stream(
            query=query,
            model=model,
            provider=provider,
            user_id=ctx.request.user_id,
        ):
            await self._publisher.publish_chunk(ctx.request.request_id, event)
            chunk_count += 1

        # Publish completion signal
        await self._publisher.publish_completion(ctx.request.request_id)

        logger.info(
            "Stream completed successfully",
            request_id=ctx.request.request_id,
            chunk_count=chunk_count,
            elapsed_seconds=ctx.elapsed_seconds,
        )


# =============================================================================
# LAYER 5: WORKER LIFECYCLE
# Manages consumer loop and coordination
# =============================================================================

class ConsumerLoop:
    """
    Manages the consumer loop lifecycle.

    Responsibility:
        Runs the main consumption loop.
        Handles polling, error recovery, and graceful shutdown.

    Design Pattern:
        Uses flag-based shutdown for graceful termination.
        Implements error recovery with backoff.
        Sequential message processing for clean resource management.
    """

    def __init__(
        self,
        queue: MessageQueue,
        processor: MessageProcessor,
        config: WorkerConfig,
        consumer_name: str,
    ):
        """
        Initialize consumer loop.

        Args:
            queue: Message queue for consuming messages
            processor: Message processor for handling messages
            config: Worker configuration
            consumer_name: Unique consumer identifier
        """
        self._queue = queue
        self._processor = processor
        self._config = config
        self._consumer_name = consumer_name
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """
        Start consumer loop.

        Continuously polls queue for messages and processes them.
        Runs until stop() is called or shutdown event is set.

        Error Handling:
            Catches all exceptions to prevent loop termination.
            Applies backoff on errors to prevent tight error loops.
        """
        self._running = True
        self._shutdown_event.clear()

        logger.info(
            "Consumer loop started",
            consumer=self._consumer_name,
            batch_size=self._config.batch_size,
            poll_interval_ms=self._config.poll_interval_ms,
        )

        while self._running and not self._shutdown_event.is_set():
            try:
                await self._consume_batch()
            except asyncio.CancelledError:
                # Graceful shutdown requested
                logger.info(
                    "Consumer loop cancelled",
                    consumer=self._consumer_name,
                )
                break
            except Exception as e:
                # Log error and backoff before retrying
                logger.error(
                    "Consumer loop error, backing off",
                    consumer=self._consumer_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                await asyncio.sleep(self._config.error_backoff_seconds)

        logger.info(
            "Consumer loop stopped",
            consumer=self._consumer_name,
        )

    def stop(self) -> None:
        """
        Signal consumer loop to stop gracefully.

        Sets flags to exit loop after current batch completes.
        """
        self._running = False
        self._shutdown_event.set()
        logger.info(
            "Consumer loop stop requested",
            consumer=self._consumer_name,
        )

    async def _consume_batch(self) -> None:
        """
        Consume and process batch of messages.

        Polls queue for messages and processes each sequentially.

        Design Rationale:
            Sequential processing respects connection pool limits cleanly.
            Parallel processing could cause connection pool thrashing.
            Batch size is small (5) for streaming responsiveness.
        """
        messages = await self._queue.consume(
            consumer_name=self._consumer_name,
            batch_size=self._config.batch_size,
            block_ms=self._config.poll_interval_ms,
        )

        if not messages:
            # No messages - brief sleep to prevent tight loop
            await asyncio.sleep(0.1)
            return

        logger.debug(
            "Consumed message batch",
            consumer=self._consumer_name,
            batch_size=len(messages),
        )

        # Process each message sequentially
        # Sequential processing ensures clean connection pool management
        for message in messages:
            if not self._running or self._shutdown_event.is_set():
                # Shutdown requested - stop processing
                logger.info(
                    "Shutdown requested, stopping batch processing",
                    consumer=self._consumer_name,
                    remaining_messages=len(messages),
                )
                break

            await self._processor.process(message)


# =============================================================================
# LAYER 6: PUBLIC API
# Clean interface for worker lifecycle management
# =============================================================================

class QueueConsumerWorker:
    """
    Background worker that processes queued streaming requests.

    Consumes requests from queue, executes streaming LLM calls,
    and publishes results to Redis Pub/Sub channels for real-time delivery.

    Usage:
        # Basic usage
        worker = QueueConsumerWorker()
        await worker.initialize()
        await worker.start()  # Blocks until stopped

        # In another task/signal handler:
        worker.stop()

        # With custom orchestrator (for testing)
        worker = QueueConsumerWorker(orchestrator_factory=mock_orchestrator)
        await worker.initialize()
        await worker.start()

    Architecture:
        - Layered design with clear separation of concerns
        - Each component has single responsibility
        - All dependencies injected explicitly
        - Testable in isolation
        - Context managers for automatic resource cleanup

    Lifecycle:
        1. Create instance
        2. Call initialize() to set up dependencies
        3. Call start() to begin processing (blocks)
        4. Call stop() from another task to shutdown
        5. Optionally call cleanup() to release resources
    """

    QUEUE_TOPIC = "streaming_requests_failover"
    QUEUE_GROUP = "streaming_failover_consumers"

    def __init__(self, orchestrator_factory: Callable[[], StreamOrchestrator] | None = None):
        """
        Initialize worker.

        Args:
            orchestrator_factory: Optional factory for stream orchestrator.
                                 Used for testing and dependency injection.
        """
        settings = get_settings()

        # Build configuration from settings
        self._config = WorkerConfig(
            max_retries=getattr(settings, 'QUEUE_FAILOVER_MAX_RETRIES', 5),
            timeout_seconds=getattr(settings, 'QUEUE_FAILOVER_TIMEOUT_SECONDS', 30),
            base_delay_ms=getattr(settings, 'QUEUE_FAILOVER_BASE_DELAY_MS', 100),
            max_backoff_ms=getattr(settings, 'QUEUE_FAILOVER_MAX_BACKOFF_MS', 5000),
            batch_size=5,  # Smaller batch for streaming responsiveness
            poll_interval_ms=2000,
            error_backoff_seconds=5,
            shutdown_timeout_seconds=5.0,
        )

        # Generate unique consumer name
        # Format: worker-{hostname}-{instance_id}
        self._consumer_name = f"worker-{socket.gethostname()}-{id(self)}"

        # Components (initialized in initialize())
        self._queue: MessageQueue | None = None
        self._redis: RedisClient | None = None
        self._consumer_loop: ConsumerLoop | None = None
        self._orchestrator_factory = orchestrator_factory

        # State
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize worker and all dependencies.

        Must be called before start().

        Sets up:
            - Message queue connection
            - Redis connection
            - Component layers (executor, publisher, etc.)
            - Consumer loop

        Raises:
            Exception: If initialization fails
        """
        if self._initialized:
            logger.debug("Worker already initialized, skipping")
            return

        logger.info(
            "Initializing worker",
            consumer=self._consumer_name,
        )

        try:
            # Initialize queue
            self._queue = get_message_queue(
                topic=self.QUEUE_TOPIC,
                group_name=self.QUEUE_GROUP,
            )
            await self._queue.initialize()

            # Initialize Redis
            self._redis = get_redis_client()
            await self._redis.connect()

            # Build component layers
            executor = StreamExecutor(self._orchestrator_factory)
            publisher = StreamPublisher(self._redis)
            connection_mgr = ConnectionManager(get_connection_pool_manager())
            retry_strategy = RetryStrategy(self._queue, publisher, self._config)

            processor = MessageProcessor(
                executor=executor,
                publisher=publisher,
                connection_mgr=connection_mgr,
                retry_strategy=retry_strategy,
                queue=self._queue,
                config=self._config,
                metrics=get_metrics_collector(),
            )

            self._consumer_loop = ConsumerLoop(
                queue=self._queue,
                processor=processor,
                config=self._config,
                consumer_name=self._consumer_name,
            )

            self._initialized = True

            logger.info(
                "Worker initialized successfully",
                consumer=self._consumer_name,
                config={
                    "max_retries": self._config.max_retries,
                    "timeout_seconds": self._config.timeout_seconds,
                    "batch_size": self._config.batch_size,
                    "poll_interval_ms": self._config.poll_interval_ms,
                }
            )

        except Exception as e:
            logger.error(
                "Worker initialization failed",
                consumer=self._consumer_name,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            raise

    async def start(self) -> None:
        """
        Start worker consumer loop.

        Blocks until stop() is called from another task.

        Raises:
            RuntimeError: If initialize() not called first
        """
        if not self._initialized:
            raise RuntimeError(
                "Worker not initialized. Call initialize() first."
            )

        logger.info(
            "Starting worker",
            consumer=self._consumer_name,
        )

        await self._consumer_loop.start()

    def stop(self) -> None:
        """
        Signal worker to stop gracefully.

        Consumer loop will complete current batch and exit.
        Does not block - use await start() to wait for completion.
        """
        if self._consumer_loop:
            self._consumer_loop.stop()
        else:
            logger.warning(
                "Stop called but consumer loop not initialized",
                consumer=self._consumer_name,
            )

    async def cleanup(self) -> None:
        """
        Clean up worker resources.

        Closes connections and releases resources.
        Should be called after stop() completes.
        """
        logger.info(
            "Cleaning up worker resources",
            consumer=self._consumer_name,
        )

        # Close Redis connection
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.error(
                    "Error closing Redis connection",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # Queue cleanup if needed
        # (Most queue implementations handle cleanup automatically)

        self._initialized = False

        logger.info(
            "Worker cleanup complete",
            consumer=self._consumer_name,
        )


# =============================================================================
# GLOBAL INSTANCE MANAGEMENT (Singleton Pattern)
# =============================================================================

_worker_instance: QueueConsumerWorker | None = None
_worker_task: asyncio.Task | None = None


async def start_queue_consumer_worker() -> QueueConsumerWorker:
    """
    Start global queue consumer worker instance.

    Implements singleton pattern for worker lifecycle management.

    Returns:
        QueueConsumerWorker: Running worker instance

    Design Rationale:
        Singleton ensures only one worker per process.
        Multiple workers would compete for same messages.
        Global instance simplifies lifecycle management in FastAPI.
    """
    global _worker_instance, _worker_task

    if _worker_instance is None:
        _worker_instance = QueueConsumerWorker()
        await _worker_instance.initialize()

    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_instance.start())
        logger.info("Worker task started")

    return _worker_instance


async def stop_queue_consumer_worker() -> None:
    """
    Stop global queue consumer worker instance.

    Waits up to configured timeout for graceful shutdown.
    Cancels task if timeout exceeded.
    Cleans up resources.
    """
    global _worker_instance, _worker_task

    if _worker_instance:
        _worker_instance.stop()

    if _worker_task:
        try:
            # Wait for graceful shutdown
            timeout = (
                _worker_instance._config.shutdown_timeout_seconds
                if _worker_instance
                else 5.0
            )
            await asyncio.wait_for(_worker_task, timeout=timeout)
            logger.info("Worker task completed gracefully")
        except asyncio.TimeoutError:
            logger.warning(
                "Worker shutdown timeout, cancelling task",
                timeout_seconds=timeout,
            )
            _worker_task.cancel()
            try:
                await _worker_task
            except asyncio.CancelledError:
                logger.info("Worker task cancelled")

    # Cleanup resources
    if _worker_instance:
        await _worker_instance.cleanup()

    _worker_instance = None
    _worker_task = None

    logger.info("Worker shutdown complete")
