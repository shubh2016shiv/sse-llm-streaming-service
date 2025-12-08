"""
Stream Orchestrator Service - Educational Documentation
========================================================

WHAT IS THE STREAM ORCHESTRATOR?
---------------------------------
The StreamOrchestrator is the HEART of this SSE streaming application. It's the
central coordinator that manages the complete lifecycle of every streaming request
from start to finish.

Think of it as a symphony conductor - it doesn't play the instruments itself,
but it coordinates all the different components (cache, providers, validators,
trackers) to work together harmoniously.

WHY IS THIS FILE SO CRUCIAL?
-----------------------------
This file is critical because it:
1. Orchestrates the entire request pipeline (6 distinct stages)
2. Integrates all major system components (cache, providers, metrics, etc.)
3. Handles errors gracefully to prevent cascading failures
4. Ensures consistent behavior across all streaming requests
5. Provides observability through detailed tracking and logging

If this file has bugs, the entire streaming system fails. That's why we need
comprehensive documentation to understand every step.

THE COMPLETE REQUEST LIFECYCLE:
--------------------------------
Every streaming request goes through these 6 stages:

┌─────────────────────────────────────────────────────────────────┐
│ STAGE 1: VALIDATION                                             │
│ - Validate query length, model name, connection limits          │
│ - Reject invalid requests early (fail fast principle)           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 2: CACHE LOOKUP                                           │
│ - Check L1 cache (in-memory) for instant response               │
│ - Check L2 cache (Redis) for fast response                      │
│ - If found: Return cached response immediately (skip stages 3-5)│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 3: RATE LIMITING                                          │
│ - Verify rate limits (handled by middleware)                    │
│ - Log verification for observability                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 4: PROVIDER SELECTION                                     │
│ - Select healthy LLM provider (OpenAI, Anthropic, etc.)         │
│ - Check circuit breaker states                                  │
│ - Implement failover if preferred provider is down              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 5: LLM STREAMING                                          │
│ - Call LLM provider's streaming API                             │
│ - Stream chunks to client in real-time                          │
│ - Send periodic heartbeats to keep connection alive             │
│ - Collect full response for caching                             │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 6: CLEANUP & CACHING                                      │
│ - Cache the complete response for future requests               │
│ - Collect execution metrics and statistics                      │
│ - Clean up thread-local data                                    │
│ - Send completion event to client                               │
└─────────────────────────────────────────────────────────────────┘

DEPENDENCY INJECTION PATTERN:
------------------------------
This class uses constructor-based dependency injection (DI). Instead of creating
its own dependencies (cache, providers, etc.), they're passed in during construction.

Benefits:
- Testability: Easy to inject mock dependencies for testing
- Flexibility: Can swap implementations without changing this code
- Loose Coupling: This class doesn't know implementation details of dependencies
- Explicit Dependencies: All dependencies are visible in the constructor

This module orchestrates the complete lifecycle of an SSE streaming request from
validation through caching, rate limiting, provider selection, streaming, and cleanup.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from src.application.validators.stream_validator import StreamRequestValidator as RequestValidator
from src.core.config.constants import (
    SSE_EVENT_CHUNK,
    SSE_EVENT_COMPLETE,
    SSE_EVENT_ERROR,
    SSE_EVENT_STATUS,
    SSE_HEARTBEAT_INTERVAL,
)
from src.core.config.settings import Settings
from src.core.exceptions import AllProvidersDownError, SSEBaseError
from src.core.logging.logger import clear_thread_id, get_logger, log_stage, set_thread_id
from src.core.observability.execution_tracker import ExecutionTracker
from src.infrastructure.cache.cache_manager import CacheManager
from src.llm_providers.base_provider import ProviderFactory
from src.llm_stream.models.stream_request import SSEEvent, StreamRequest

logger = get_logger(__name__)


# ============================================================================
# STREAM ORCHESTRATOR CLASS
# ============================================================================


class StreamOrchestrator:
    """
    Central coordinator for SSE streaming request lifecycle.

    ORCHESTRATOR PATTERN:
    ---------------------
    The orchestrator pattern is used when you need to coordinate multiple
    services/components to complete a complex workflow. The orchestrator:
    - Knows the workflow steps
    - Calls each service in the right order
    - Handles errors and retries
    - Manages state across the workflow

    In our case, the workflow is the 6-stage streaming pipeline, and the
    services are: validator, cache, provider factory, execution tracker.

    ASYNC GENERATOR PATTERN:
    ------------------------
    The main `stream()` method is an async generator (uses yield).
    This allows us to:
    - Stream events to the client as they occur (low latency)
    - Handle long-running operations without blocking
    - Send multiple events over time (status, chunks, completion)
    - Clean up resources even if client disconnects

    THREAD SAFETY:
    --------------
    This class is NOT thread-safe, but that's okay because:
    - FastAPI runs in async mode (single-threaded event loop)
    - Each request gets its own execution context
    - Shared state (active_connections) is only modified in async context

    If you need thread safety, use asyncio.Lock() for shared state.
    """

    def __init__(
        self,
        cache_manager: CacheManager,
        provider_factory: ProviderFactory,
        execution_tracker: ExecutionTracker,
        settings: Settings,
        validator: RequestValidator | None = None,
    ):
        """
        Initialize orchestrator with dependency injection.

        DEPENDENCY INJECTION EXPLAINED:
        -------------------------------
        Instead of creating dependencies inside this class:
            self._cache = CacheManager()  # BAD: Hard to test, tightly coupled

        We receive them as constructor parameters:
            def __init__(self, cache_manager: CacheManager):  # GOOD: Testable, flexible
                self._cache = cache_manager

        This allows:
        1. Testing: Inject mock cache for unit tests
        2. Flexibility: Swap Redis cache for Memcached without changing this code
        3. Initialization Control: Caller controls when/how dependencies are created
        4. Explicit Dependencies: Clear what this class needs to function

        Args:
            cache_manager: Manages L1 (memory) and L2 (Redis) caching
            provider_factory: Creates and manages LLM provider instances
            execution_tracker: Tracks performance metrics for each stage
            settings: Application configuration (timeouts, limits, etc.)
            validator: Validates requests (created if not provided)
        """
        # Store injected dependencies
        # The underscore prefix (_cache) indicates these are private/internal
        self._cache = cache_manager
        self._provider_factory = provider_factory
        self._tracker = execution_tracker
        self.settings = settings

        # Create validator if not provided (optional dependency)
        # This provides a sensible default while still allowing injection
        self._validator = validator or RequestValidator()

        # Initialize connection counter
        # This tracks how many active streaming connections we have
        # Used for connection limits and capacity monitoring
        self._active_connections = 0

        # Flag indicating dependencies are initialized
        # In this design, we assume the caller initialized all dependencies
        # before passing them to us (see app.py lifespan function)
        self._initialized = True

        # Priority queue for managing concurrent requests
        # PRIORITY QUEUE PATTERN:
        # -----------------------
        # In production systems, not all requests are equal:
        # - "high": Premium users, critical operations
        # - "normal": Regular users
        # - "low": Background tasks, analytics
        #
        # Priority queues ensure high-priority requests are processed first
        # even when the system is under load.
        #
        # asyncio.PriorityQueue automatically sorts items by priority.
        # Lower numbers = higher priority (0 is highest).
        self._priority_queues: dict[str, asyncio.Queue] = {
            "high": asyncio.PriorityQueue(),
            "normal": asyncio.PriorityQueue(),
            "low": asyncio.PriorityQueue(),
        }

        logger.info("StreamOrchestrator initialized with priority-based processing")

    # ========================================================================
    # MAIN STREAMING METHOD - THE HEART OF THE ORCHESTRATOR
    # ========================================================================

    async def stream(self, request: StreamRequest) -> AsyncGenerator[SSEEvent, None]:
        """
        Execute the complete 6-stage streaming lifecycle.

        ASYNC GENERATOR EXPLAINED:
        --------------------------
        This method is an async generator because:
        1. It's defined with 'async def' (can use await)
        2. It uses 'yield' to produce values (not return)
        3. It produces multiple values over time (not just one)

        How it works:
        - Each 'yield' sends an SSEEvent to the client
        - Execution pauses at each yield
        - Resumes when client is ready for next event
        - Continues until function completes or raises exception

        Why use async generator for streaming?
        - Low latency: Client sees events as they happen
        - Memory efficient: Don't buffer entire response
        - Cancellable: If client disconnects, generator stops
        - Non-blocking: Other requests can be processed concurrently

        RETURN TYPE ANNOTATION:
        -----------------------
        AsyncGenerator[SSEEvent, None] means:
        - AsyncGenerator: This is an async generator
        - SSEEvent: Each yielded value is an SSEEvent
        - None: This generator doesn't accept sent values (via .send())

        THE 6-STAGE PIPELINE:
        ---------------------
        Each stage is wrapped in a context manager (with statement) that:
        - Records start time
        - Executes the stage logic
        - Records end time and duration
        - Logs stage completion
        - Handles stage-specific errors

        This provides detailed observability into where time is spent.

        Args:
            request: StreamRequest containing:
                - query: User's question/prompt
                - model: LLM model to use (gpt-4, claude-3, etc.)
                - provider: Preferred provider (optional)
                - thread_id: Unique request identifier
                - user_id: User identifier for rate limiting

        Yields:
            SSEEvent: Events sent to client in SSE format:
                - status: "validated", "streaming", etc.
                - chunk: LLM response chunks
                - error: Error information
                - complete: Final completion event

        Raises:
            SSEBaseError: Application-specific errors (cache, provider, etc.)
            Exception: Unexpected errors (caught and converted to error events)
        """
        # ====================================================================
        # SETUP: Initialize request context
        # ====================================================================
        # Extract thread ID for correlation across logs and metrics
        # The thread_id allows us to trace a single request through:
        # - Application logs
        # - Metrics/dashboards
        # - Distributed tracing systems
        thread_id = request.thread_id

        # Set thread ID in thread-local storage for logging
        # This makes the thread_id available to all log calls in this context
        # without passing it explicitly to every function
        set_thread_id(thread_id)

        # Increment active connection counter
        # This is used for:
        # 1. Connection limit enforcement (reject if too many)
        # 2. Capacity monitoring (how loaded is the system?)
        # 3. Metrics/dashboards (current load)
        self._active_connections += 1

        try:
            # ================================================================
            # STAGE 1: REQUEST VALIDATION
            # ================================================================
            # PURPOSE: Reject invalid requests early (fail fast principle)
            # DURATION: ~1-5ms (very fast, just validation logic)
            #
            # Why validate first?
            # - Saves resources (don't cache/process invalid requests)
            # - Better error messages (specific validation errors)
            # - Security (prevent injection attacks, DoS, etc.)
            #
            # What we validate:
            # 1. Query length (min/max bounds)
            # 2. Model name (is it supported?)
            # 3. Connection limits (are we at capacity?)

            with self._tracker.track_stage("1", "Request validation", thread_id):
                # VALIDATION 1.1: Query validation
                # Check query is not empty and within size limits
                # This prevents:
                # - Empty queries (waste of resources)
                # - Extremely long queries (DoS attack, excessive costs)
                self._validator.validate_query(request.query)

                # VALIDATION 1.2: Model validation
                # Check the requested model is supported
                # This prevents:
                # - Typos in model names
                # - Requests for deprecated models
                # - Requests for models we don't have access to
                self._validator.validate_model(request.model)

                # VALIDATION 1.3: Connection limit check
                # Ensure we're not exceeding max concurrent connections
                # This prevents:
                # - System overload (too many concurrent requests)
                # - Resource exhaustion (memory, file descriptors, etc.)
                # - Degraded performance for all users
                self._validator.check_connection_limit(self._active_connections)

            # Send validation success event to client
            # This lets the client know the request was accepted and is being processed
            # The client can show a "processing..." indicator
            yield SSEEvent(
                event=SSE_EVENT_STATUS, data={"status": "validated", "thread_id": thread_id}
            )

            # ================================================================
            # STAGE 2: CACHE LOOKUP
            # ================================================================
            # PURPOSE: Return cached responses instantly (if available)
            # DURATION: ~1-10ms for L1 (memory), ~10-50ms for L2 (Redis)
            #
            # CACHING STRATEGY:
            # -----------------
            # We use a two-tier cache:
            # 1. L1 Cache (In-Memory): Fastest, limited capacity
            # 2. L2 Cache (Redis): Fast, larger capacity, shared across instances
            #
            # Cache lookup flow:
            # 1. Check L1 cache (memory) - instant if found
            # 2. If not in L1, check L2 cache (Redis) - fast if found
            # 3. If found in L2, populate L1 for next time
            # 4. If not found anywhere, proceed to LLM call
            #
            # Why cache?
            # - Reduce LLM API costs (cached responses are free)
            # - Reduce latency (instant vs 1-5 seconds for LLM)
            # - Reduce load on LLM providers
            # - Improve reliability (cache works even if LLM is down)

            # STEP 2.1: Generate cache key
            # The cache key uniquely identifies this request
            # Format: "response:{hash(query)}:{model}"
            # Same query + same model = same cache key = cache hit
            cache_key = CacheManager.generate_cache_key("response", request.query, request.model)

            # STEP 2.2: Attempt cache lookup
            # This checks L1 (memory) first, then L2 (Redis) if not found
            # Returns None if not found in either cache
            cached_response = await self._cache.get(cache_key, thread_id)

            # STEP 2.3: Handle cache hit (if found)
            if cached_response:
                # Cache hit! We can return the response immediately
                # This is the FASTEST path through the system
                log_stage(logger, "2", "Cache hit - returning cached response")

                # Send the cached response as a single chunk
                # We mark it as cached so client knows it's instant
                yield SSEEvent(
                    event=SSE_EVENT_CHUNK, data={"content": cached_response, "cached": True}
                )

                # Send completion event
                # This tells the client the stream is complete
                yield SSEEvent(
                    event=SSE_EVENT_COMPLETE, data={"thread_id": thread_id, "cached": True}
                )

                # EARLY RETURN: Skip stages 3-6 entirely
                # We're done! No need to call the LLM.
                # This is why caching is so powerful - it bypasses
                # the entire expensive LLM call pipeline.
                return

            # STEP 2.4: Handle cache miss
            # Not found in cache, we'll need to call the LLM
            # This is the SLOW path through the system
            log_stage(logger, "2", "Cache miss - proceeding to LLM")

            # ================================================================
            # STAGE 3: RATE LIMITING VERIFICATION
            # ================================================================
            # PURPOSE: Ensure user hasn't exceeded rate limits
            # DURATION: ~1ms (just logging, actual check is in middleware)
            #
            # RATE LIMITING STRATEGY:
            # -----------------------
            # Rate limiting is actually enforced by middleware (before this code runs).
            # If the user exceeded their rate limit, the middleware would have
            # rejected the request with a 429 error.
            #
            # This stage just logs that rate limiting was verified.
            # Why log it?
            # - Observability: See that rate limiting is working
            # - Metrics: Track how often users hit rate limits
            # - Debugging: Understand request flow
            #
            # Why is rate limiting in middleware instead of here?
            # - Fail fast: Reject before expensive processing
            # - Consistent: Applied to all endpoints, not just streaming
            # - Separation of concerns: Middleware handles cross-cutting concerns

            with self._tracker.track_stage("3", "Rate limit verification", thread_id):
                log_stage(logger, "3", "Rate limit verified", user_id=request.user_id)

            # ================================================================
            # STAGE 4: PROVIDER SELECTION
            # ================================================================
            # PURPOSE: Select a healthy LLM provider with failover
            # DURATION: ~5-20ms (circuit breaker state checks)
            #
            # PROVIDER SELECTION STRATEGY:
            # ----------------------------
            # We support multiple LLM providers (OpenAI, Anthropic, etc.) for:
            # - Reliability: If one provider is down, use another
            # - Cost optimization: Route to cheapest provider
            # - Feature support: Some models only available on certain providers
            #
            # Selection algorithm:
            # 1. If user specified a preferred provider, try it first
            # 2. Check if preferred provider's circuit breaker is closed (healthy)
            # 3. If preferred provider is down, select another healthy provider
            # 4. If all providers are down, raise AllProvidersDownError
            #
            # CIRCUIT BREAKER PATTERN:
            # ------------------------
            # Each provider has a circuit breaker that tracks failures:
            # - CLOSED: Provider is healthy, allow requests
            # - OPEN: Provider is failing, block requests (fail fast)
            # - HALF_OPEN: Testing if provider recovered
            #
            # This prevents cascading failures where we keep calling a failing
            # provider, wasting time and resources.

            with self._tracker.track_stage("4", "Provider selection", thread_id):
                # STEP 4.1: Select provider with failover
                # This method implements the selection algorithm described above
                # It returns a healthy provider or None if all are down
                provider = await self._select_provider(request.provider, request.model)

                # STEP 4.2: Handle all providers down
                # If no healthy provider is available, we can't fulfill the request
                if not provider:
                    raise AllProvidersDownError(
                        message="All providers are unavailable", thread_id=thread_id
                    )

                # STEP 4.3: Log selected provider
                # This helps with debugging and understanding provider usage patterns
                log_stage(logger, "4", f"Selected provider: {provider.name}", model=request.model)

            # ================================================================
            # STAGE 5: LLM STREAMING
            # ================================================================
            # PURPOSE: Call LLM API and stream response chunks to client
            # DURATION: ~1-10 seconds (depends on response length and LLM speed)
            #
            # STREAMING EXPLAINED:
            # --------------------
            # Instead of waiting for the complete response, we stream it chunk by chunk:
            # 1. LLM generates first token → send to client immediately
            # 2. LLM generates second token → send to client immediately
            # 3. Continue until LLM signals completion
            #
            # Benefits:
            # - Low latency: User sees response start immediately
            # - Better UX: Progressive loading (like ChatGPT)
            # - Lower memory: Don't buffer entire response
            # - Cancellable: Can stop if user navigates away
            #
            # HEARTBEAT MECHANISM:
            # --------------------
            # For long-running streams, we send periodic heartbeats to:
            # - Keep connection alive (prevent proxy timeouts)
            # - Detect client disconnections
            # - Show client the stream is still active

            # Initialize response collection
            # We collect all chunks to cache the complete response later
            full_response = []
            chunk_count = 0

            with self._tracker.track_stage("5", "LLM streaming", thread_id):
                # STEP 5.1: Start heartbeat task
                # This runs concurrently with streaming to send periodic heartbeats
                # asyncio.create_task() schedules the coroutine to run in the background
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(thread_id))

                try:
                    # STEP 5.2: Stream from LLM provider
                    # ASYNC FOR LOOP:
                    # ---------------
                    # 'async for' is used to iterate over an async generator
                    # The provider.stream() method is an async generator that:
                    # - Calls the LLM API
                    # - Yields chunks as they arrive
                    # - Handles retries and errors
                    #
                    # Each iteration:
                    # 1. Waits for next chunk from LLM (await)
                    # 2. Receives chunk object
                    # 3. Processes chunk
                    # 4. Yields chunk to client
                    # 5. Repeats until LLM signals completion
                    async for chunk in provider.stream(
                        query=request.query, model=request.model, thread_id=thread_id
                    ):
                        # STEP 5.2.1: Track chunk
                        chunk_count += 1

                        # STEP 5.2.2: Collect chunk for caching
                        # We need the full response to cache it later
                        full_response.append(chunk.content)

                        # STEP 5.2.3: Send chunk to client
                        # This yields an SSEEvent that gets sent to the client immediately
                        # The client sees this chunk in real-time
                        yield SSEEvent(
                            event=SSE_EVENT_CHUNK,
                            data={
                                "content": chunk.content,
                                "chunk_index": chunk_count,
                                "finish_reason": chunk.finish_reason,
                            },
                        )

                        # STEP 5.2.4: Check for completion
                        # If LLM signals completion (finish_reason is set), stop streaming
                        # finish_reason can be:
                        # - "stop": Natural completion
                        # - "length": Hit max token limit
                        # - "content_filter": Content policy violation
                        if chunk.finish_reason:
                            break

                finally:
                    # STEP 5.3: Stop heartbeat task
                    # FINALLY BLOCK:
                    # --------------
                    # This ALWAYS runs, even if:
                    # - An exception occurs
                    # - We break out of the loop
                    # - The client disconnects
                    #
                    # We MUST cancel the heartbeat task to prevent:
                    # - Resource leaks (task running forever)
                    # - Logging spam (heartbeats after stream ends)

                    # Cancel the heartbeat task
                    heartbeat_task.cancel()

                    # Wait for cancellation to complete
                    # This ensures the task is fully cleaned up
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        # CancelledError is expected when we cancel a task
                        # We catch and ignore it (this is normal)
                        pass

            # ================================================================
            # STAGE 6: CLEANUP AND CACHING
            # ================================================================
            # PURPOSE: Cache response and collect metrics
            # DURATION: ~10-50ms (Redis write)
            #
            # CLEANUP TASKS:
            # --------------
            # 1. Cache the complete response for future requests
            # 2. Collect execution metrics (duration, chunk count, etc.)
            # 3. Clean up thread-local data
            # 4. Send completion event to client

            with self._tracker.track_stage("6", "Cleanup and caching", thread_id):
                # STEP 6.1: Assemble complete response
                # Join all chunks into a single string
                # This is what we'll cache for future requests
                response_text = "".join(full_response)

                # STEP 6.2: Cache the response
                # Store in cache with TTL (time-to-live)
                # This makes future identical requests instant
                #
                # Cache write flow:
                # 1. Write to L1 cache (memory) - instant
                # 2. Write to L2 cache (Redis) - async, ~10-50ms
                # 3. Set expiration (TTL) so cache doesn't grow forever
                await self._cache.set(
                    cache_key,
                    response_text,
                    ttl=self.settings.cache.CACHE_RESPONSE_TTL,
                    thread_id=thread_id,
                )

                # STEP 6.3: Get execution summary
                # This collects metrics from all stages:
                # - Total duration
                # - Per-stage durations
                # - Stage count
                # - Thread ID
                summary = self._tracker.get_execution_summary(thread_id)

            # STEP 6.4: Send completion event
            # This tells the client the stream is complete
            # Includes summary statistics for client-side metrics
            yield SSEEvent(
                event=SSE_EVENT_COMPLETE,
                data={
                    "thread_id": thread_id,
                    "chunk_count": chunk_count,
                    "total_length": len(response_text),
                    "duration_ms": summary.get("total_duration_ms", 0),
                },
            )

            # STEP 6.5: Log completion
            # This helps with monitoring and debugging
            logger.info(
                "Stream completed successfully",
                thread_id=thread_id,
                chunk_count=chunk_count,
                duration_ms=summary.get("total_duration_ms", 0),
            )

        # ====================================================================
        # ERROR HANDLING
        # ====================================================================
        # We have two levels of error handling:
        # 1. Application errors (SSEBaseError): Expected errors we handle gracefully
        # 2. Unexpected errors (Exception): Programming errors, system failures

        except SSEBaseError as e:
            # APPLICATION ERRORS:
            # -------------------
            # These are expected errors that can occur during normal operation:
            # - CacheError: Cache is down
            # - ProviderError: LLM provider failed
            # - ValidationError: Invalid request
            # - RateLimitError: User exceeded limits
            # - AllProvidersDownError: All LLM providers unavailable
            #
            # For these errors:
            # - Log the error with context
            # - Send error event to client (with details)
            # - Don't crash the application

            logger.error(f"Stream failed: {e}", thread_id=thread_id)

            # Send error event to client
            # Client can display error message to user
            yield SSEEvent(
                event=SSE_EVENT_ERROR,
                data={"error": type(e).__name__, "message": str(e), "thread_id": thread_id},
            )

        except Exception as e:
            # UNEXPECTED ERRORS:
            # ------------------
            # These are programming errors or system failures:
            # - AttributeError: Bug in code (accessing non-existent attribute)
            # - TypeError: Bug in code (wrong type passed to function)
            # - ConnectionError: Network failure
            # - MemoryError: Out of memory
            #
            # For these errors:
            # - Log full details (including stack trace)
            # - Send generic error to client (don't expose internals)
            # - Don't crash the application

            logger.error(f"Unexpected error: {e}", thread_id=thread_id)

            # Send generic error to client
            # We don't expose internal error details for security
            yield SSEEvent(
                event=SSE_EVENT_ERROR,
                data={
                    "error": "internal_error",
                    "message": "An unexpected error occurred",
                    "thread_id": thread_id,
                },
            )

        finally:
            # ================================================================
            # FINAL CLEANUP
            # ================================================================
            # FINALLY BLOCK:
            # --------------
            # This ALWAYS runs, no matter what:
            # - Success: Normal completion
            # - Error: Exception occurred
            # - Cancellation: Client disconnected
            #
            # Critical cleanup tasks that MUST happen:
            # 1. Decrement connection counter
            # 2. Clear thread-local data
            # 3. Clear thread ID from logging context

            # CLEANUP 1: Decrement active connections
            # This ensures our connection count stays accurate
            # Even if errors occur, we must decrement to avoid:
            # - Connection leaks (counter keeps growing)
            # - False connection limit errors (think we're at capacity when we're not)
            self._active_connections -= 1

            # CLEANUP 2: Clear execution tracker data
            # This frees memory used for tracking this request
            # Prevents memory leaks from accumulating tracking data
            self._tracker.clear_thread_data(thread_id)

            # CLEANUP 3: Clear thread ID from logging context
            # This ensures subsequent logs don't incorrectly include this thread_id
            clear_thread_id()

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    async def _select_provider(self, preferred: str | None, model: str):
        """
        Select a healthy LLM provider with failover support.

        PROVIDER SELECTION ALGORITHM:
        -----------------------------
        This method implements intelligent provider selection:

        1. If user specified a preferred provider:
           a. Try to get that provider from the factory
           b. Check its circuit breaker state
           c. If circuit is CLOSED (healthy), use it
           d. If circuit is OPEN (unhealthy), skip to step 2

        2. If no preferred provider or it's unhealthy:
           a. Ask factory for any healthy provider
           b. Factory checks all providers' circuit breakers
           c. Returns first healthy provider found
           d. Returns None if all providers are down

        CIRCUIT BREAKER STATES:
        -----------------------
        - "closed": Provider is healthy, allow requests
        - "open": Provider is failing, block requests
        - "half_open": Testing if provider recovered

        Why check circuit breaker?
        - Fail fast: Don't waste time calling a failing provider
        - Prevent cascading failures: Don't overload a struggling provider
        - Better UX: Faster failover to healthy provider

        Args:
            preferred: User's preferred provider name (optional)
            model: Model name (used for provider compatibility check)

        Returns:
            Provider instance if healthy provider found, None otherwise
        """
        # STEP 1: Try preferred provider if specified
        if preferred:
            try:
                # Get the preferred provider from factory
                provider = self._provider_factory.get(preferred)

                # Check circuit breaker state
                # await is needed because circuit state might be stored in Redis
                circuit_state = await provider.get_circuit_state()

                # If circuit is not open, provider is healthy
                # (closed or half_open are both acceptable)
                if circuit_state != "open":
                    return provider

            except Exception:
                # If anything goes wrong getting preferred provider:
                # - Provider not found
                # - Circuit breaker error
                # - Network error
                # Just continue to step 2 (try other providers)
                # We use bare except here because we want to be resilient
                pass

        # STEP 2: Get any healthy provider
        # This method checks all providers and returns first healthy one
        # It excludes the preferred provider if we already tried it
        return await self._provider_factory.get_healthy_provider(
            exclude=[preferred] if preferred else None
        )

    async def _heartbeat_loop(self, thread_id: str):
        """
        Send periodic heartbeats to keep connection alive.

        HEARTBEAT PATTERN:
        ------------------
        For long-running connections (like SSE), we need heartbeats to:

        1. Keep connection alive:
           - Proxies/load balancers timeout idle connections
           - Heartbeats show connection is still active
           - Prevents premature connection closure

        2. Detect disconnections:
           - If heartbeat fails to send, client disconnected
           - We can stop processing and clean up

        3. Show progress:
           - Client knows stream is still active
           - Can show "processing..." indicator

        IMPLEMENTATION:
        ---------------
        This is an infinite loop that:
        1. Sleeps for HEARTBEAT_INTERVAL seconds
        2. Logs a heartbeat message
        3. Repeats forever

        The loop is cancelled when streaming completes (see stage 5 finally block).

        ASYNCIO.SLEEP():
        ----------------
        We use asyncio.sleep() instead of time.sleep() because:
        - asyncio.sleep() is non-blocking (other requests can run)
        - time.sleep() would block the entire event loop (bad!)

        Args:
            thread_id: Request identifier for logging correlation
        """
        while True:
            # Sleep for heartbeat interval
            # This is non-blocking - other requests can run during sleep
            await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)

            # Log heartbeat at debug level
            # We use debug level because heartbeats are frequent and not critical
            # In production, debug logs are usually disabled to reduce noise
            log_stage(logger, "5.H", "Heartbeat", level="debug")

    # ========================================================================
    # PROPERTIES AND STATS
    # ========================================================================

    @property
    def active_connections(self) -> int:
        """
        Get current number of active streaming connections.

        PROPERTY DECORATOR:
        -------------------
        @property makes this method accessible like an attribute:

            count = orchestrator.active_connections  # Looks like attribute
            # Instead of:
            count = orchestrator.active_connections()  # Looks like method

        Use @property when:
        - Method has no parameters
        - Method is fast (no expensive computation)
        - Logically represents an attribute of the object

        Returns:
            int: Number of currently active streaming connections
        """
        return self._active_connections

    def get_stats(self) -> dict[str, Any]:
        """
        Get orchestrator statistics for monitoring and debugging.

        STATS FOR OBSERVABILITY:
        ------------------------
        This method provides a snapshot of orchestrator state:
        - active_connections: Current load
        - initialized: Is orchestrator ready?
        - cache_stats: Cache hit rate, size, etc.

        Used by:
        - Health check endpoints
        - Monitoring dashboards
        - Debugging (what's the current state?)
        - Capacity planning (how loaded are we?)

        Returns:
            dict: Statistics dictionary with current state
        """
        return {
            "active_connections": self._active_connections,
            "initialized": self._initialized,
            "cache_stats": self._cache.stats() if self._cache else None,
        }
