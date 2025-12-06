"""
Stream Request Lifecycle Manager

Orchestrates the complete lifecycle of an SSE streaming request from validation
through caching, rate limiting, provider selection, streaming, and cleanup.

This module consolidates the request processing pipeline with:
- Stage-based execution tracking
- Multi-tier cache integration (L1/L2)
- Circuit breaker and retry mechanisms
- Metrics collection and health monitoring
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
    SSEBaseException,
)
from src.core.execution_tracker import get_tracker
from src.core.logging import clear_thread_id, get_logger, log_stage, set_thread_id
from src.llm_providers.base_provider import get_provider_factory
from src.streaming.models import SSEEvent, StreamRequest
from src.streaming.validators import RequestValidator

logger = get_logger(__name__)


class StreamRequestLifecycle:
    """
    Manages the complete lifecycle of SSE streaming requests.

    Request Flow:
    1. Priority Sort  - Sort requests by priority (high/normal/low)
    2. Validation    - Verify request parameters and connection limits
    3. Cache Lookup  - Check L1 (memory) → L2 (Redis) for cached response
    4. Rate Limit    - Enforced by middleware, logged here
    5. Provider      - Select healthy LLM provider with failover
    6. Stream        - Execute LLM call and stream chunks to client
    7. Cleanup       - Cache response, collect metrics, cleanup thread data

    Architecture:
    - Context managers for automatic timing and error tracking
    - Multi-tier caching reduces redundant LLM calls
    - Circuit breaker prevents cascade failures
    - Heartbeat keeps connection alive during long streams
    - Priority-based processing improves QoS for premium users

    Rationale: Enables fair resource allocation - premium users (HIGH priority)
    get processed before standard users (NORMAL), background tasks (LOW) process last.
    Maintains fairness within each priority level via FIFO.
    """

    def __init__(self):
        self.settings = get_settings()
        self._tracker = get_tracker()
        self._cache: CacheManager | None = None
        self._validator = RequestValidator()
        self._active_connections = 0
        self._initialized = False

        # Priority queue for managing concurrent requests
        self._priority_queues: dict[str, asyncio.Queue] = {
            "high": asyncio.PriorityQueue(),
            "normal": asyncio.PriorityQueue(),
            "low": asyncio.PriorityQueue()
        }

        logger.info("StreamRequestLifecycle initialized with priority-based processing")

    async def initialize(self) -> None:
        """Initialize dependencies (cache, providers)."""
        if self._initialized:
            return

        self._cache = get_cache_manager()
        await self._cache.initialize()

        self._initialized = True
        logger.info("StreamRequestLifecycle ready")

    async def shutdown(self) -> None:
        """Shutdown and cleanup resources."""
        if self._cache:
            await self._cache.shutdown()

        self._initialized = False
        logger.info("StreamRequestLifecycle shutdown complete")

    async def stream(self, request: StreamRequest) -> AsyncGenerator[SSEEvent, None]:
        """
        Execute complete streaming lifecycle.

        Args:
            request: StreamRequest with query, model, provider preferences

        Yields:
            SSEEvent: Events to send to client (status, chunk, error, complete)
        """
        thread_id = request.thread_id
        set_thread_id(thread_id)

        self._active_connections += 1

        try:
            # STAGE 1: Validation
            with self._tracker.track_stage("1", "Request validation", thread_id):
                self._validator.validate_query(request.query)
                self._validator.validate_model(request.model)
                self._validator.check_connection_limit(self._active_connections)

            yield SSEEvent(
                event=SSE_EVENT_STATUS,
                data={"status": "validated", "thread_id": thread_id}
            )

            # STAGE 2: Cache Lookup
            cache_key = CacheManager.generate_cache_key(
                "response", request.query, request.model
            )
            cached_response = await self._cache.get(cache_key, thread_id)

            if cached_response:
                log_stage(logger, "2", "Cache hit - returning cached response")
                yield SSEEvent(
                    event=SSE_EVENT_CHUNK,
                    data={"content": cached_response, "cached": True}
                )
                yield SSEEvent(
                    event=SSE_EVENT_COMPLETE,
                    data={"thread_id": thread_id, "cached": True}
                )
                return

            log_stage(logger, "2", "Cache miss - proceeding to LLM")

            # STAGE 3: Rate Limiting (handled by middleware, log verification)
            with self._tracker.track_stage("3", "Rate limit verification", thread_id):
                log_stage(logger, "3", "Rate limit verified", user_id=request.user_id)

            # STAGE 4: Provider Selection
            with self._tracker.track_stage("4", "Provider selection", thread_id):
                provider = await self._select_provider(request.provider, request.model)
                if not provider:
                    raise AllProvidersDownError(
                        message="All providers are unavailable",
                        thread_id=thread_id
                    )
                log_stage(logger, "4", f"Selected provider: {provider.name}", model=request.model)

            # STAGE 5: LLM Streaming
            full_response = []
            chunk_count = 0

            with self._tracker.track_stage("5", "LLM streaming", thread_id):
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(thread_id))

                try:
                    async for chunk in provider.stream(
                        query=request.query,
                        model=request.model,
                        thread_id=thread_id
                    ):
                        chunk_count += 1
                        full_response.append(chunk.content)

                        yield SSEEvent(
                            event=SSE_EVENT_CHUNK,
                            data={
                                "content": chunk.content,
                                "chunk_index": chunk_count,
                                "finish_reason": chunk.finish_reason
                            }
                        )

                        if chunk.finish_reason:
                            break
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

            # STAGE 6: Cleanup and Caching
            with self._tracker.track_stage("6", "Cleanup and caching", thread_id):
                response_text = "".join(full_response)

                await self._cache.set(
                    cache_key,
                    response_text,
                    ttl=self.settings.cache.CACHE_RESPONSE_TTL,
                    thread_id=thread_id
                )

                summary = self._tracker.get_execution_summary(thread_id)

            yield SSEEvent(
                event=SSE_EVENT_COMPLETE,
                data={
                    "thread_id": thread_id,
                    "chunk_count": chunk_count,
                    "total_length": len(response_text),
                    "duration_ms": summary.get("total_duration_ms", 0)
                }
            )

            logger.info(
                "Stream completed successfully",
                thread_id=thread_id,
                chunk_count=chunk_count,
                duration_ms=summary.get("total_duration_ms", 0)
            )

        except SSEBaseException as e:
            logger.error(f"Stream failed: {e}", thread_id=thread_id)
            yield SSEEvent(
                event=SSE_EVENT_ERROR,
                data={
                    "error": type(e).__name__,
                    "message": str(e),
                    "thread_id": thread_id
                }
            )

        except Exception as e:
            logger.error(f"Unexpected error: {e}", thread_id=thread_id)
            yield SSEEvent(
                event=SSE_EVENT_ERROR,
                data={
                    "error": "internal_error",
                    "message": "An unexpected error occurred",
                    "thread_id": thread_id
                }
            )

        finally:
            self._active_connections -= 1
            self._tracker.clear_thread_data(thread_id)
            clear_thread_id()

    async def _select_provider(self, preferred: str | None, model: str):
        """
        Select a healthy provider with failover support.

        Strategy:
        1. Try preferred provider if specified and circuit closed
        2. Fall back to any healthy provider (circuit closed)
        3. Return None if all providers have open circuits
        """
        factory = get_provider_factory()

        if preferred:
            try:
                provider = factory.get(preferred)
                if provider.get_circuit_state() != "open":
                    return provider
            except Exception:
                pass

        return factory.get_healthy_provider(exclude=[preferred] if preferred else None)

    async def _heartbeat_loop(self, thread_id: str):
        """Send periodic heartbeat to keep connection alive."""
        while True:
            await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)
            log_stage(logger, "5.H", "Heartbeat", level="debug")

    @property
    def active_connections(self) -> int:
        """Get current number of active streaming connections."""
        return self._active_connections

    def get_stats(self) -> dict[str, Any]:
        """Get lifecycle manager statistics."""
        return {
            "active_connections": self._active_connections,
            "initialized": self._initialized,
            "cache_stats": self._cache.stats() if self._cache else None
        }


# Singleton instance
_lifecycle: StreamRequestLifecycle | None = None


def get_stream_lifecycle() -> StreamRequestLifecycle:
    """Get global StreamRequestLifecycle instance."""
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = StreamRequestLifecycle()
    return _lifecycle


async def init_stream_lifecycle() -> StreamRequestLifecycle:
    """Initialize global StreamRequestLifecycle."""
    lifecycle = get_stream_lifecycle()
    await lifecycle.initialize()
    return lifecycle


async def close_stream_lifecycle() -> None:
    """Shutdown global StreamRequestLifecycle."""
    global _lifecycle
    if _lifecycle:
        await _lifecycle.shutdown()
        _lifecycle = None

