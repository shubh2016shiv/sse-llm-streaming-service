"""
Streaming Service - Educational Documentation
==============================================

WHAT IS THIS SERVICE?
---------------------
StreamingService encapsulates the core business logic for SSE streaming.
It handles:
1. Connection pool management (acquire/release)
2. Queue failover when pool is exhausted
3. SSE event generation
4. Error handling and metrics recording

WHY EXTRACT THIS FROM ROUTES?
-----------------------------
BEFORE (in route):
- 400+ lines mixing HTTP concerns with business logic
- Hard to test (requires HTTP mocking)
- Cognitive overload (too much in one place)

AFTER (in service):
- Route handles HTTP only (~150 lines)
- Service handles business logic (testable, focused)
- Each layer has one responsibility

GOOGLE-LEVEL PATTERNS:
-----------------------
1. **Dependency Injection**: Service receives dependencies (doesn't create them)
2. **Resource Management**: Connection pool acquire/release in try/finally
3. **Error Resilience**: Graceful degradation to queue failover
4. **Observability**: Structured logging with context
5. **Async Generators**: Memory-efficient streaming

ARCHITECTURE:
-------------
Route → StreamingService → Orchestrator → Providers → LLM APIs
                        → ConnectionPool
                        → QueueHandler (failover)
"""

from collections.abc import AsyncGenerator
from typing import Any

import structlog

from src.application.api.models.streaming import (
    ResilienceLayer,
)
from src.core.exceptions import (
    ConnectionPoolExhaustedError,
    SSEBaseError,
    UserConnectionLimitError,
)
from src.core.resilience.connection_pool_manager import get_connection_pool_manager
from src.core.resilience.queue_request_handler import get_queue_request_handler
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector
from src.llm_stream.models.stream_request import SSEEvent, StreamRequest
from src.llm_stream.services.stream_orchestrator import StreamOrchestrator

# ============================================================================
# MODULE LOGGER
# ============================================================================
# Structured logging with context for observability.
# All log entries include service name for filtering in log aggregators.

logger = structlog.get_logger(__name__)


# ============================================================================
# STREAMING SERVICE: Core Business Logic
# ============================================================================


class StreamingService:
    """
    Service for handling SSE streaming requests.

    RESPONSIBILITIES:
    -----------------
    1. Acquire and release connection pool slots
    2. Handle queue failover when pool exhausted
    3. Generate SSE events from orchestrator stream
    4. Record metrics for monitoring

    DESIGN PRINCIPLES:
    ------------------
    - Stateless: No instance variables for request-specific data
    - Dependency injection: Receives orchestrator, doesn't create it
    - Error resilience: Graceful degradation with queue failover
    - Resource safety: Connection pool slots always released

    USAGE:
    ------
    service = StreamingService(orchestrator)
    async for event in service.create_stream(request, user_id, thread_id):
        yield event
    """

    def __init__(self, orchestrator: StreamOrchestrator):
        """
        Initialize streaming service.

        Args:
            orchestrator: Stream orchestrator for LLM interactions
                          (injected by dependency injection from app state)
        """
        self.orchestrator = orchestrator
        self._pool_manager = get_connection_pool_manager()
        self._metrics = get_metrics_collector()

        logger.info(
            "streaming_service_initialized", context="Service ready to handle streaming requests"
        )

    # ========================================================================
    # MAIN ENTRY POINT: Create Stream
    # ========================================================================

    async def create_stream(
        self,
        request_model: Any,
        user_id: str,
        thread_id: str,
    ) -> tuple[AsyncGenerator[str, None], ResilienceLayer]:
        """
        Create an SSE stream for a user request.

        FLOW:
        -----
        1. Try to acquire connection from pool
        2. If pool exhausted → Fallback to queue
        3. Start streaming with acquired resources
        4. Return generator and resilience layer indicator

        CONNECTION POOL PATTERN:
        ------------------------
        The connection pool limits concurrent connections to prevent:
        - Memory exhaustion (each connection uses RAM)
        - File descriptor exhaustion
        - Downstream service overload

        QUEUE FAILOVER (LAYER 3 DEFENSE):
        ----------------------------------
        Instead of rejecting requests when pool is full:
        - Enqueue request to Redis/Kafka
        - Worker processes from queue when capacity available
        - Client receives stream via Redis Pub/Sub

        Args:
            request_model: Validated StreamRequestModel from route
            user_id: User identifier for rate limiting
            thread_id: Request correlation ID

        Returns:
            Tuple of (async_generator, resilience_layer)
        """
        try:
            # ================================================================
            # STEP 1: Acquire Connection from Pool
            # ================================================================
            # This may raise ConnectionPoolExhaustedError or UserConnectionLimitError
            logger.debug("connection_pool_acquire_started", user_id=user_id, thread_id=thread_id)

            await self._pool_manager.acquire_connection(user_id=user_id, thread_id=thread_id)

            logger.debug(
                "connection_pool_acquired",
                user_id=user_id,
                thread_id=thread_id,
                stage="LAYER2.SUCCESS",
            )

            # ================================================================
            # STEP 2: Return Direct Stream Generator
            # ================================================================
            # Pool slot acquired, use direct streaming path
            generator = self._generate_stream(
                request_model=request_model,
                user_id=user_id,
                thread_id=thread_id,
            )

            return generator, ResilienceLayer.DIRECT

        except (ConnectionPoolExhaustedError, UserConnectionLimitError) as e:
            # ================================================================
            # LAYER 3 DEFENSE: Queue Failover
            # ================================================================
            # Pool exhausted - activate queue failover instead of rejecting
            logger.warning(
                "connection_pool_limit_reached_activating_queue_failover",
                stage="LAYER3.ACTIVATE",
                thread_id=thread_id,
                user_id=user_id,
                reason=str(e),
            )

            generator = self._generate_queue_stream(
                request_model=request_model,
                user_id=user_id,
                thread_id=thread_id,
            )

            return generator, ResilienceLayer.QUEUE_FAILOVER

    # ========================================================================
    # STREAM GENERATORS
    # ========================================================================

    async def _generate_stream(
        self,
        request_model: Any,
        user_id: str,
        thread_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Generate SSE events via direct orchestrator stream.

        ASYNC GENERATORS IN PYTHON:
        ---------------------------
        An async generator is a function that:
        1. Is defined with 'async def'
        2. Uses 'yield' to produce values
        3. Can use 'await' for async operations

        How it works:
        - Each 'yield' pauses execution and returns a value
        - The caller can iterate with 'async for'
        - Execution resumes after the yield when next value is requested

        WHY USE ASYNC GENERATORS FOR SSE?
        ----------------------------------
        - Perfect for streaming data as it becomes available
        - Non-blocking (doesn't tie up the event loop)
        - Memory efficient (doesn't load entire response into memory)
        - Natural fit for the SSE protocol

        RESOURCE MANAGEMENT:
        --------------------
        The try/finally ensures connection pool slot is ALWAYS released,
        even if an error occurs or the client disconnects.
        """
        # Track active connection in metrics
        self._metrics.increment_connections()

        try:
            # ================================================================
            # Create StreamRequest from validated input
            # ================================================================
            stream_request = StreamRequest(
                query=request_model.query,
                model=request_model.model,
                provider=request_model.provider,
                thread_id=thread_id,
                user_id=user_id,
            )

            # ================================================================
            # Stream LLM Response Chunks
            # ================================================================
            # The orchestrator handles:
            # - Cache lookup (L1 in-memory, L2 Redis)
            # - Rate limiting per user/provider
            # - Provider selection and failover
            # - Actual LLM API calls
            # - Cache storage for future requests
            async for event in self.orchestrator.stream(stream_request):
                # Format the event as SSE protocol
                # Output: "event: message\ndata: {...}\n\n"
                yield event.format()

            # ================================================================
            # Send Completion Signal
            # ================================================================
            # This tells the client the stream is complete (not an error).
            # The client's EventSource can detect this and stop listening.
            yield "data: [DONE]\n\n"

            # Record successful completion
            self._metrics.record_request(
                "success", request_model.provider or "auto", request_model.model
            )

            logger.debug("stream_completed_successfully", thread_id=thread_id, user_id=user_id)

        except SSEBaseError as e:
            # ================================================================
            # Handle Application-Specific Errors
            # ================================================================
            # These are known error types (cache errors, provider errors, etc.)
            # Send an error event to the client with context.
            error_event = self._create_error_event(error_type=type(e).__name__, message=str(e))
            yield error_event.format()

            # Record error metrics
            self._metrics.record_request(
                "error", request_model.provider or "auto", request_model.model
            )
            self._metrics.record_error(type(e).__name__, "stream")

            logger.warning(
                "stream_error_application",
                thread_id=thread_id,
                error_type=type(e).__name__,
                error_message=str(e),
            )

        except Exception as e:
            # ================================================================
            # Handle Unexpected Errors
            # ================================================================
            # Don't expose internal error details to the client (security)
            error_event = self._create_error_event(
                error_type="internal_error", message="An unexpected error occurred"
            )
            yield error_event.format()

            # Record error metrics
            self._metrics.record_request(
                "error", request_model.provider or "auto", request_model.model
            )
            self._metrics.record_error("internal_error", "stream")

            # Log detailed error for debugging
            import traceback

            logger.error(
                "stream_error_unexpected",
                thread_id=thread_id,
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=traceback.format_exc(),
            )

        finally:
            # ================================================================
            # CLEANUP: Always Release Resources
            # ================================================================
            # This ALWAYS runs, even if there's an error or client disconnects.
            # Critical for preventing resource leaks.

            # Release connection pool slot
            await self._pool_manager.release_connection(thread_id=thread_id, user_id=user_id)

            # Decrement active connections metric
            self._metrics.decrement_connections()

            logger.debug("stream_resources_released", thread_id=thread_id, user_id=user_id)

    async def _generate_queue_stream(
        self,
        request_model: Any,
        user_id: str,
        thread_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Generate SSE events via queue failover mechanism.

        QUEUE FAILOVER FLOW:
        --------------------
        1. Enqueue request payload to "streaming_requests_failover" topic
        2. QueueConsumerWorker picks it up when capacity available
        3. Worker streams response to Redis Pub/Sub channel
        4. This generator subscribes and yields chunks from Pub/Sub

        WHY QUEUE FAILOVER?
        -------------------
        Instead of returning 429 "Too Many Requests":
        - Client gets a response (better UX)
        - Request isn't lost (reliability)
        - Load is smoothed out (backpressure)

        The trade-off is slightly higher latency for queued requests,
        but this is better than complete rejection.
        """
        try:
            queue_handler = get_queue_request_handler()

            # This returns an async generator that yields SSE events
            # from the queue worker via Redis Pub/Sub
            stream_generator = queue_handler.queue_and_stream(
                user_id=user_id, thread_id=thread_id, payload=request_model.model_dump()
            )

            async for chunk in stream_generator:
                yield chunk

            logger.debug(
                "queue_stream_completed",
                thread_id=thread_id,
                user_id=user_id,
                stage="LAYER3.COMPLETE",
            )

        except Exception as queue_error:
            # ================================================================
            # Queue Failover Failed
            # ================================================================
            # If even the queue fails (Redis down, etc.), send error event
            logger.error(
                "queue_failover_failed",
                stage="LAYER3.ERROR",
                thread_id=thread_id,
                error=str(queue_error),
            )

            error_event = self._create_error_event(
                error_type="queue_failover_failed",
                message="Request queuing failed. Please try again later.",
            )
            yield error_event.format()

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _create_error_event(self, error_type: str, message: str) -> SSEEvent:
        """
        Create a standardized SSE error event.

        SSE ERROR EVENT FORMAT:
        -----------------------
        event: error
        data: {"error": "error_type", "message": "description"}

        This allows clients to:
        1. Distinguish errors from normal data events
        2. Parse structured error information
        3. Display user-friendly error messages
        """
        return SSEEvent(event="error", data={"error": error_type, "message": message})


# ============================================================================
# DEPENDENCY INJECTION: Singleton Pattern
# ============================================================================
# Why singleton?
# - StreamingService is stateless (safe to share)
# - Connection pool manager is already singleton
# - Metrics collector is already singleton

_streaming_service: StreamingService | None = None


def get_streaming_service(orchestrator: StreamOrchestrator) -> StreamingService:
    """
    Get or create the StreamingService instance.

    DEPENDENCY INJECTION PATTERN:
    -----------------------------
    Unlike MetricsService, StreamingService needs the orchestrator
    which is only available from app.state (via request).

    So we accept orchestrator as parameter and create service on demand.
    The service is cached for reuse within same orchestrator.

    Args:
        orchestrator: StreamOrchestrator from app.state

    Returns:
        StreamingService instance
    """
    global _streaming_service

    if _streaming_service is None:
        _streaming_service = StreamingService(orchestrator=orchestrator)
        logger.info(
            "streaming_service_singleton_created", context="Service will be reused for all requests"
        )

    return _streaming_service
