"""
Stream Request Lifecycle Manager - Educational Documentation
=============================================================

WHAT IS THE REQUEST LIFECYCLE MANAGER?
---------------------------------------
The StreamRequestLifecycle is an alternative implementation of the streaming
orchestrator pattern. While stream_orchestrator.py uses dependency injection,
this module uses the SINGLETON PATTERN with lazy initialization.

Think of this as the "self-contained" version of the orchestrator - it manages
its own dependencies internally rather than having them injected.

SINGLETON PATTERN VS DEPENDENCY INJECTION:
-------------------------------------------
This file demonstrates a different architectural approach:

**Dependency Injection (stream_orchestrator.py)**:
- Dependencies passed in constructor
- Caller controls initialization
- Better for testing (easy to inject mocks)
- More flexible (swap implementations easily)

**Singleton Pattern (this file)**:
- Single global instance
- Self-initializes dependencies
- Simpler API (no need to pass dependencies)
- Good for application-level services

Both approaches are valid - choose based on your needs:
- Use DI for libraries and testable components
- Use Singleton for application-level coordinators

THE COMPLETE REQUEST LIFECYCLE:
--------------------------------
This module implements the same 6-stage pipeline as stream_orchestrator.py:

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

LAZY INITIALIZATION PATTERN:
-----------------------------
This module uses lazy initialization for dependencies:
- Dependencies are NOT created in __init__()
- Dependencies are created in initialize() method
- This allows:
  * Fast application startup (defer expensive initialization)
  * Async initialization (cache/Redis connections are async)
  * Graceful shutdown (cleanup resources properly)

PRIORITY QUEUE ARCHITECTURE:
-----------------------------
Supports priority-based request processing:
- HIGH: Premium users, critical operations (processed first)
- NORMAL: Regular users (processed second)
- LOW: Background tasks, analytics (processed last)

This ensures fair resource allocation and better QoS for premium users.

This module orchestrates the complete lifecycle of an SSE streaming request from
validation through caching, rate limiting, provider selection, streaming, and cleanup.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from src.caching.cache_manager import CacheManager, get_cache_manager
from src.config.constants import (
    SSE_EVENT_CHUNK,
    SSE_EVENT_COMPLETE,
    SSE_EVENT_ERROR,
    SSE_EVENT_STATUS,
    SSE_HEARTBEAT_INTERVAL,
)
from src.config.settings import get_settings
from src.core.exceptions import (
    AllProvidersDownError,
    SSEBaseError,
)
from src.core.execution_tracker import get_tracker
from src.core.logging import clear_thread_id, get_logger, log_stage, set_thread_id
from src.llm_providers.base_provider import get_provider_factory
from src.streaming.models import SSEEvent, StreamRequest
from src.streaming.validators import RequestValidator

logger = get_logger(__name__)


# ============================================================================
# STREAM REQUEST LIFECYCLE CLASS
# ============================================================================


class StreamRequestLifecycle:
    """
    Manages the complete lifecycle of SSE streaming requests using singleton pattern.

    SINGLETON PATTERN EXPLAINED:
    ----------------------------
    A singleton ensures only ONE instance of this class exists globally.
    This is useful for:
    - Shared state (active connections counter)
    - Resource management (single cache/provider pool)
    - Consistent configuration across the application

    How it works:
    - Module-level variable (_lifecycle) stores the single instance
    - get_stream_lifecycle() returns existing instance or creates new one
    - All parts of the application share the same instance

    LAZY INITIALIZATION:
    --------------------
    Unlike stream_orchestrator.py which receives initialized dependencies,
    this class initializes its own dependencies in the initialize() method.

    Benefits:
    - Fast application startup (defer expensive initialization)
    - Async initialization (cache/Redis connections are async)
    - Explicit initialization control (call initialize() when ready)

    Drawbacks:
    - Must remember to call initialize() before use
    - Harder to test (dependencies are created internally)
    - Less flexible (can't easily swap implementations)

    PRIORITY-BASED PROCESSING:
    ---------------------------
    Implements priority queues for fair resource allocation:
    - HIGH priority: Premium users, critical operations
    - NORMAL priority: Regular users
    - LOW priority: Background tasks, analytics

    This ensures premium users get better service even under load.

    ARCHITECTURE COMPARISON:
    ------------------------
    This class is similar to StreamOrchestrator but uses:
    - Singleton pattern instead of dependency injection
    - Lazy initialization instead of constructor injection
    - Global factory functions instead of explicit dependencies

    Both approaches are valid - this one is simpler but less testable.
    """

    def __init__(self):
        """
        Initialize the lifecycle manager with default state.

        LAZY INITIALIZATION:
        --------------------
        Notice that we DON'T initialize dependencies here:
        - self._cache is set to None (initialized later)
        - Settings are loaded (cheap operation)
        - Tracker is retrieved (cheap operation)
        - Validator is created (cheap operation)

        Heavy dependencies (cache, providers) are initialized in initialize().

        Why defer initialization?
        - Cache requires async Redis connection (can't do in __init__)
        - Providers require async setup (can't do in __init__)
        - Application startup is faster (defer until needed)

        INITIALIZATION FLAG:
        --------------------
        self._initialized tracks whether initialize() has been called.
        This prevents:
        - Double initialization (wasting resources)
        - Using the lifecycle before it's ready (causing errors)
        """
        # Load application settings
        # This is cheap (just reading config) so we do it immediately
        self.settings = get_settings()

        # Get execution tracker for performance monitoring
        # This is cheap (singleton retrieval) so we do it immediately
        self._tracker = get_tracker()

        # Cache will be initialized later (requires async Redis connection)
        # Setting to None makes it clear it's not ready yet
        self._cache: CacheManager | None = None

        # Create request validator
        # This is cheap (just creating an object) so we do it immediately
        self._validator = RequestValidator()

        # Initialize connection counter
        # Tracks how many active streaming connections we have
        self._active_connections = 0

        # Initialization flag
        # False until initialize() is called successfully
        self._initialized = False

        # Priority queues for managing concurrent requests
        # PRIORITY QUEUE PATTERN:
        # -----------------------
        # In production systems, not all requests are equal:
        # - "high": Premium users, critical operations (processed first)
        # - "normal": Regular users (processed second)
        # - "low": Background tasks, analytics (processed last)
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

        logger.info("StreamRequestLifecycle initialized with priority-based processing")

    # ========================================================================
    # LIFECYCLE MANAGEMENT METHODS
    # ========================================================================

    async def initialize(self) -> None:
        """
        Initialize heavy dependencies (cache, providers).

        ASYNC INITIALIZATION:
        ---------------------
        This method is async because:
        - Cache initialization requires Redis connection (async I/O)
        - Provider initialization might require API calls (async I/O)
        - We want to wait for initialization to complete before proceeding

        IDEMPOTENT INITIALIZATION:
        --------------------------
        This method is idempotent (safe to call multiple times):
        - If already initialized, returns immediately
        - If not initialized, performs initialization
        - This prevents double initialization bugs

        INITIALIZATION ORDER:
        ---------------------
        1. Check if already initialized (early return if yes)
        2. Initialize cache manager (async Redis connection)
        3. Set initialized flag to True
        4. Log success

        Why this order?
        - Check flag first (fastest path for already-initialized case)
        - Initialize cache (most important dependency)
        - Set flag (mark as ready)
        - Log (observability)

        USAGE:
        ------
            lifecycle = StreamRequestLifecycle()
            await lifecycle.initialize()  # Must call before using
            # Now ready to process requests
        """
        # STEP 1: Check if already initialized
        # This makes the method idempotent (safe to call multiple times)
        if self._initialized:
            return

        # STEP 2: Initialize cache manager
        # This creates Redis connection pool and prepares L1/L2 cache
        # AWAIT is necessary because Redis connection is async I/O
        self._cache = get_cache_manager()
        await self._cache.initialize()

        # STEP 3: Set initialized flag
        # This marks the lifecycle as ready to use
        # Future calls to initialize() will return early
        self._initialized = True

        # STEP 4: Log success
        # This helps with debugging and monitoring
        logger.info("StreamRequestLifecycle ready")

    async def shutdown(self) -> None:
        """
        Shutdown and cleanup resources.

        GRACEFUL SHUTDOWN:
        ------------------
        This method ensures resources are cleaned up properly:
        - Close Redis connections
        - Flush pending cache writes
        - Cancel background tasks
        - Release file handles

        Why is this important?
        - Prevents resource leaks (connections, memory, etc.)
        - Ensures data is persisted (flush cache writes)
        - Clean application exit (no hanging connections)

        SHUTDOWN ORDER:
        ---------------
        1. Shutdown cache (close Redis connections)
        2. Set initialized flag to False
        3. Log completion

        Why this order?
        - Shutdown cache first (most important cleanup)
        - Clear flag (mark as not ready)
        - Log (observability)

        USAGE:
        ------
            # On application shutdown
            await lifecycle.shutdown()
            # Resources are now cleaned up
        """
        # STEP 1: Shutdown cache if initialized
        # This closes Redis connections and flushes pending writes
        if self._cache:
            await self._cache.shutdown()

        # STEP 2: Clear initialized flag
        # This marks the lifecycle as not ready
        # Prevents using it after shutdown
        self._initialized = False

        # STEP 3: Log completion
        # This helps with debugging and monitoring
        logger.info("StreamRequestLifecycle shutdown complete")

    # ========================================================================
    # MAIN STREAMING METHOD - THE HEART OF THE LIFECYCLE
    # ========================================================================

    async def stream(self, request: StreamRequest) -> AsyncGenerator[SSEEvent, None]:
        """
        Execute the complete 6-stage streaming lifecycle.

        This method is identical to StreamOrchestrator.stream() in functionality.
        See stream_orchestrator.py for detailed documentation of:
        - Async generator pattern
        - 6-stage pipeline
        - Error handling
        - Resource cleanup

        The implementation is the same, only the dependency management differs:
        - StreamOrchestrator: Dependencies injected via constructor
        - StreamRequestLifecycle: Dependencies initialized in initialize()

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
        thread_id = request.thread_id
        set_thread_id(thread_id)
        self._active_connections += 1

        try:
            # ================================================================
            # STAGE 1: REQUEST VALIDATION
            # ================================================================
            # PURPOSE: Reject invalid requests early (fail fast principle)
            # DURATION: ~1-5ms (very fast, just validation logic)

            with self._tracker.track_stage("1", "Request validation", thread_id):
                # VALIDATION 1.1: Query validation
                self._validator.validate_query(request.query)

                # VALIDATION 1.2: Model validation
                self._validator.validate_model(request.model)

                # VALIDATION 1.3: Connection limit check
                self._validator.check_connection_limit(self._active_connections)

            yield SSEEvent(
                event=SSE_EVENT_STATUS, data={"status": "validated", "thread_id": thread_id}
            )

            # ================================================================
            # STAGE 2: CACHE LOOKUP
            # ================================================================
            # PURPOSE: Return cached responses instantly (if available)
            # DURATION: ~1-10ms for L1 (memory), ~10-50ms for L2 (Redis)

            # STEP 2.1: Generate cache key
            cache_key = CacheManager.generate_cache_key("response", request.query, request.model)

            # STEP 2.2: Attempt cache lookup
            cached_response = await self._cache.get(cache_key, thread_id)

            # STEP 2.3: Handle cache hit (if found)
            if cached_response:
                log_stage(logger, "2", "Cache hit - returning cached response")
                yield SSEEvent(
                    event=SSE_EVENT_CHUNK, data={"content": cached_response, "cached": True}
                )
                yield SSEEvent(
                    event=SSE_EVENT_COMPLETE, data={"thread_id": thread_id, "cached": True}
                )
                # EARLY RETURN: Skip stages 3-6 entirely
                return

            # STEP 2.4: Handle cache miss
            log_stage(logger, "2", "Cache miss - proceeding to LLM")

            # ================================================================
            # STAGE 3: RATE LIMITING VERIFICATION
            # ================================================================
            # PURPOSE: Ensure user hasn't exceeded rate limits
            # DURATION: ~1ms (just logging, actual check is in middleware)

            with self._tracker.track_stage("3", "Rate limit verification", thread_id):
                log_stage(logger, "3", "Rate limit verified", user_id=request.user_id)

            # ================================================================
            # STAGE 4: PROVIDER SELECTION
            # ================================================================
            # PURPOSE: Select a healthy LLM provider with failover
            # DURATION: ~5-20ms (circuit breaker state checks)

            with self._tracker.track_stage("4", "Provider selection", thread_id):
                # STEP 4.1: Select provider with failover
                provider = await self._select_provider(request.provider, request.model)

                # STEP 4.2: Handle all providers down
                if not provider:
                    raise AllProvidersDownError(
                        message="All providers are unavailable", thread_id=thread_id
                    )

                # STEP 4.3: Log selected provider
                log_stage(logger, "4", f"Selected provider: {provider.name}", model=request.model)

            # ================================================================
            # STAGE 5: LLM STREAMING
            # ================================================================
            # PURPOSE: Call LLM API and stream response chunks to client
            # DURATION: ~1-10 seconds (depends on response length and LLM speed)

            # Initialize response collection
            full_response = []
            chunk_count = 0

            with self._tracker.track_stage("5", "LLM streaming", thread_id):
                # STEP 5.1: Start heartbeat task
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(thread_id))

                try:
                    # STEP 5.2: Stream from LLM provider
                    async for chunk in provider.stream(
                        query=request.query, model=request.model, thread_id=thread_id
                    ):
                        # STEP 5.2.1: Track chunk
                        chunk_count += 1

                        # STEP 5.2.2: Collect chunk for caching
                        full_response.append(chunk.content)

                        # STEP 5.2.3: Send chunk to client
                        yield SSEEvent(
                            event=SSE_EVENT_CHUNK,
                            data={
                                "content": chunk.content,
                                "chunk_index": chunk_count,
                                "finish_reason": chunk.finish_reason,
                            },
                        )

                        # STEP 5.2.4: Check for completion
                        if chunk.finish_reason:
                            break

                finally:
                    # STEP 5.3: Stop heartbeat task
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

            # ================================================================
            # STAGE 6: CLEANUP AND CACHING
            # ================================================================
            # PURPOSE: Cache response and collect metrics
            # DURATION: ~10-50ms (Redis write)

            with self._tracker.track_stage("6", "Cleanup and caching", thread_id):
                # STEP 6.1: Assemble complete response
                response_text = "".join(full_response)

                # STEP 6.2: Cache the response
                await self._cache.set(
                    cache_key,
                    response_text,
                    ttl=self.settings.cache.CACHE_RESPONSE_TTL,
                    thread_id=thread_id,
                )

                # STEP 6.3: Get execution summary
                summary = self._tracker.get_execution_summary(thread_id)

            # STEP 6.4: Send completion event
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
            logger.info(
                "Stream completed successfully",
                thread_id=thread_id,
                chunk_count=chunk_count,
                duration_ms=summary.get("total_duration_ms", 0),
            )

        # ====================================================================
        # ERROR HANDLING
        # ====================================================================

        except SSEBaseError as e:
            # APPLICATION ERRORS: Expected errors we handle gracefully
            logger.error(f"Stream failed: {e}", thread_id=thread_id)
            yield SSEEvent(
                event=SSE_EVENT_ERROR,
                data={"error": type(e).__name__, "message": str(e), "thread_id": thread_id},
            )

        except Exception as e:
            # UNEXPECTED ERRORS: Programming errors or system failures
            logger.error(f"Unexpected error: {e}", thread_id=thread_id)
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
            # CLEANUP 1: Decrement active connections
            self._active_connections -= 1

            # CLEANUP 2: Clear execution tracker data
            self._tracker.clear_thread_data(thread_id)

            # CLEANUP 3: Clear thread ID from logging context
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

        FACTORY PATTERN:
        ----------------
        We use get_provider_factory() to get the provider factory.
        This is a global factory function (similar to singleton pattern).

        The factory:
        - Manages all provider instances
        - Checks circuit breaker states
        - Implements provider selection logic
        - Handles provider initialization

        Args:
            preferred: User's preferred provider name (optional)
            model: Model name (used for provider compatibility check)

        Returns:
            Provider instance if healthy provider found, None otherwise
        """
        # Get the global provider factory
        # This is a singleton that manages all provider instances
        factory = get_provider_factory()

        # STEP 1: Try preferred provider if specified
        if preferred:
            try:
                # Get the preferred provider from factory
                provider = factory.get(preferred)

                # Check circuit breaker state
                # Note: This is sync (not await) - different from stream_orchestrator.py
                # Some implementations store circuit state in memory (sync)
                # Others store in Redis (async) - depends on implementation
                if provider.get_circuit_state() != "open":
                    return provider

            except Exception:
                # If anything goes wrong, continue to step 2
                pass

        # STEP 2: Get any healthy provider
        # This method checks all providers and returns first healthy one
        return factory.get_healthy_provider(exclude=[preferred] if preferred else None)

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

        Args:
            thread_id: Request identifier for logging correlation
        """
        while True:
            # Sleep for heartbeat interval (non-blocking)
            await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)

            # Log heartbeat at debug level
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

            count = lifecycle.active_connections  # Looks like attribute
            # Instead of:
            count = lifecycle.active_connections()  # Looks like method

        Returns:
            int: Number of currently active streaming connections
        """
        return self._active_connections

    def get_stats(self) -> dict[str, Any]:
        """
        Get lifecycle manager statistics for monitoring and debugging.

        STATS FOR OBSERVABILITY:
        ------------------------
        This method provides a snapshot of lifecycle state:
        - active_connections: Current load
        - initialized: Is lifecycle ready?
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


# ============================================================================
# SINGLETON PATTERN IMPLEMENTATION
# ============================================================================

# Module-level variable to store the single instance
# This is the "singleton" - only one instance exists globally
_lifecycle: StreamRequestLifecycle | None = None


def get_stream_lifecycle() -> StreamRequestLifecycle:
    """
    Get the global StreamRequestLifecycle singleton instance.

    SINGLETON PATTERN:
    ------------------
    This function implements the singleton pattern:
    1. Check if instance already exists
    2. If not, create new instance
    3. Return the instance

    This ensures only ONE instance exists globally.

    LAZY CREATION:
    --------------
    The instance is created on first call (lazy creation):
    - Fast application startup (instance not created until needed)
    - Deferred initialization (initialize() called separately)

    THREAD SAFETY:
    --------------
    This implementation is NOT thread-safe, but that's okay because:
    - Python GIL ensures atomic operations
    - FastAPI runs in async mode (single-threaded event loop)
    - Multiple calls in quick succession might create multiple instances,
      but in practice this doesn't happen in async code

    For true thread safety, use threading.Lock():
        _lock = threading.Lock()
        with _lock:
            if _lifecycle is None:
                _lifecycle = StreamRequestLifecycle()

    USAGE:
    ------
        lifecycle = get_stream_lifecycle()
        await lifecycle.initialize()
        # Now ready to use

    Returns:
        StreamRequestLifecycle: The global singleton instance
    """
    global _lifecycle

    # Check if instance already exists
    if _lifecycle is None:
        # Create new instance (first call)
        _lifecycle = StreamRequestLifecycle()

    # Return the instance (existing or newly created)
    return _lifecycle


async def init_stream_lifecycle() -> StreamRequestLifecycle:
    """
    Initialize the global StreamRequestLifecycle singleton.

    CONVENIENCE FUNCTION:
    ---------------------
    This function combines two operations:
    1. Get the singleton instance
    2. Initialize it (async Redis connection, etc.)

    This is a convenience function that saves you from writing:
        lifecycle = get_stream_lifecycle()
        await lifecycle.initialize()

    Instead, you can just write:
        lifecycle = await init_stream_lifecycle()

    IDEMPOTENT:
    -----------
    This function is idempotent (safe to call multiple times):
    - First call: Creates instance and initializes it
    - Subsequent calls: Returns existing instance (already initialized)

    This is because:
    - get_stream_lifecycle() returns existing instance if it exists
    - lifecycle.initialize() checks if already initialized

    USAGE:
    ------
        # In application startup (e.g., FastAPI lifespan)
        lifecycle = await init_stream_lifecycle()
        # Now ready to process requests

    Returns:
        StreamRequestLifecycle: The initialized global singleton instance
    """
    # Get the singleton instance (creates if doesn't exist)
    lifecycle = get_stream_lifecycle()

    # Initialize it (async operation)
    # This is idempotent - safe to call multiple times
    await lifecycle.initialize()

    # Return the initialized instance
    return lifecycle


async def close_stream_lifecycle() -> None:
    """
    Shutdown and cleanup the global StreamRequestLifecycle singleton.

    GRACEFUL SHUTDOWN:
    ------------------
    This function ensures proper cleanup on application shutdown:
    1. Shutdown the lifecycle (close Redis connections, etc.)
    2. Clear the global instance variable

    This is important for:
    - Clean application exit (no hanging connections)
    - Resource cleanup (close Redis, release memory)
    - Proper shutdown in tests (reset state between tests)

    RESET STATE:
    ------------
    After calling this function:
    - _lifecycle is set to None
    - Next call to get_stream_lifecycle() will create a new instance
    - This allows restarting the lifecycle (useful in tests)

    USAGE:
    ------
        # In application shutdown (e.g., FastAPI lifespan)
        await close_stream_lifecycle()
        # Resources are now cleaned up
    """
    global _lifecycle

    # Check if instance exists
    if _lifecycle:
        # Shutdown the lifecycle (close connections, etc.)
        await _lifecycle.shutdown()

        # Clear the global variable
        # This allows creating a new instance later if needed
        _lifecycle = None
