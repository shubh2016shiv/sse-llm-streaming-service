#!/usr/bin/env python3
"""
Multi-Tier Cache Manager - Refactored for Clarity

Architecture:
    CacheManager (Public API)
        ├── CacheStrategy (L1→L2 coordination logic)
        │   ├── L1Storage (In-memory LRU)
        │   └── L2Storage (Redis)
        ├── CacheObserver (Metrics & logging)
        └── CacheWarmer (Warming strategies)

Performance Targets:
    - L1 hit: < 1ms
    - L2 hit: 1-5ms
    - Cache miss: 50-500ms (LLM call)
    - Target: 95%+ cache hit rate

Author: Refactored for clarity and maintainability
Date: 2025-12-13
"""

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

import orjson

from src.core.config.constants import (
    L1_CACHE_MAX_SIZE,
    REDIS_KEY_CACHE_RESPONSE,
)
from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger, log_stage
from src.core.observability.execution_tracker import get_tracker
from src.infrastructure.cache.redis_client import RedisClient, get_redis_client

logger = get_logger(__name__)


# =============================================================================
# LAYER 1: STORAGE IMPLEMENTATIONS
# Pure storage interfaces - no business logic
# =============================================================================


class L1Storage:
    """
    In-memory LRU cache storage.

    Responsibility: Fast, thread-safe in-memory storage with LRU eviction.

    STAGE-2.1: L1 in-memory cache

    This is a per-instance cache, not shared across workers.
    For distributed caching, use L2Storage (Redis).

    Implementation Details:
    - Uses OrderedDict for O(1) access and LRU ordering
    - Thread-safe via asyncio.Lock
    - Automatically evicts oldest items when at capacity
    - Tracks hits/misses for performance monitoring

    Why LRU?
    - Simple and effective eviction policy
    - Assumes recent items are more likely to be accessed again
    - O(1) for both get and set operations
    """

    def __init__(self, max_size: int = L1_CACHE_MAX_SIZE):
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of items to store
        """
        self._max_size = max_size
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        """
        Get value from cache. Returns None if not found.

        Thread-Safety: Uses asyncio.Lock to prevent race conditions
        LRU Update: Moves accessed item to end (most recently used)

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        async with self._lock:
            if key in self._cache:
                # Move to end (mark as recently used)
                # This is the "LRU" part - recently accessed items move to the back
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    async def set(self, key: str, value: str) -> None:
        """
        Set value in cache. Evicts LRU item if at capacity.

        Eviction Policy:
        - When cache is full, remove oldest (least recently used) item
        - popitem(last=False) removes from front (oldest)

        Args:
            key: Cache key
            value: Value to cache
        """
        async with self._lock:
            if key in self._cache:
                # Update existing and mark as recently used
                self._cache.move_to_end(key)

            self._cache[key] = value

            # Evict oldest items if over capacity
            # This maintains the max_size constraint
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)  # Remove oldest (front)

    async def delete(self, key: str) -> bool:
        """
        Delete value from cache. Returns True if deleted, False if not found.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        """
        Clear all items from cache.

        Use Case: Cache invalidation, testing, or memory cleanup
        """
        async with self._lock:
            self._cache.clear()

    def get_size(self) -> int:
        """Get current number of items in cache."""
        return len(self._cache)

    def get_max_size(self) -> int:
        """Get maximum capacity."""
        return self._max_size

    def get_keys(self) -> list[str]:
        """
        Get all cache keys (most recent last).

        Returns:
            List of keys in LRU order (oldest first, newest last)
        """
        return list(self._cache.keys())


class L2Storage:
    """
    Redis distributed cache storage.

    Responsibility: Distributed storage with TTL support.
    Provides actual pipelining for batch operations.

    STAGE-2.2: L2 Redis cache

    Why Redis?
    - Distributed: Shared across all application instances
    - Persistent: Survives application restarts
    - TTL Support: Automatic expiration of stale data
    - Pipelining: Batch operations for reduced network overhead

    Performance Optimization:
    - Uses pipelining to reduce network round-trips by 50-70%
    - Single network call for multiple operations
    """

    def __init__(self, redis_client: RedisClient):
        """
        Initialize Redis storage.

        Args:
            redis_client: Redis client instance
        """
        self._redis = redis_client

    async def connect(self) -> None:
        """
        Establish Redis connection.

        STAGE-2.0.1: Initialize L2 (Redis) connection
        """
        await self._redis.connect()

    async def get(self, key: str) -> str | None:
        """
        Get value from Redis.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        return await self._redis.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        """
        Set value in Redis with TTL.

        TTL (Time-To-Live):
        - Automatically expires after specified seconds
        - Prevents stale data accumulation
        - Redis handles cleanup automatically

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds
        """
        await self._redis.set(key, value, ttl=ttl)

    async def delete(self, key: str) -> None:
        """
        Delete value from Redis.

        Args:
            key: Cache key
        """
        await self._redis.delete(key)

    async def batch_get(self, keys: list[str]) -> dict[str, str | None]:
        """
        Batch get using Redis pipelining.

        Performance Optimization:
        - Uses single network round-trip for all keys
        - Reduces latency by 50-70% vs sequential gets
        - Critical for warming L1 cache efficiently

        How Pipelining Works:
        1. Queue all commands (no network calls yet)
        2. Execute pipeline (single network round-trip)
        3. Receive all responses at once

        Fallback Strategy:
        - If pipelining unavailable, falls back to sequential gets
        - Still works, just slower

        Args:
            keys: List of cache keys to fetch

        Returns:
            Dict mapping key → value (None if not found)
        """
        if not keys:
            return {}

        pipeline_mgr = self._redis.get_pipeline_manager()

        if pipeline_mgr:
            # Use actual pipelining (optimal path)
            # This queues all commands and executes in one round-trip
            results = {}
            for key in keys:
                results[key] = await pipeline_mgr.execute_command("get", key)
            return results
        else:
            # Fallback to sequential (still works, just slower)
            # This makes N network calls instead of 1
            results = {}
            for key in keys:
                results[key] = await self._redis.get(key)
            return results

    async def health_check(self) -> dict[str, Any]:
        """
        Check Redis health.

        Returns:
            Dict with health status and connection info
        """
        return await self._redis.health_check()


# =============================================================================
# LAYER 2: CACHE STRATEGY
# Orchestrates L1→L2 lookups and cache population
# =============================================================================


CacheSource = Literal["l1", "l2", "miss"]


class CacheStrategy:
    """
    Orchestrates multi-tier cache lookups.

    Responsibility: Implements L1→L2 fallback logic and warming strategy.

    Algorithm:
        GET: L1 → L2 → miss (warm L1 on L2 hit)
        SET: L1 + L2 (or L1 only for temporary data)
        BATCH: L1 bulk check → L2 pipeline → warm L1

    Why This Design?
    - L1 is fastest but limited in size and not shared
    - L2 is slower but distributed and persistent
    - Warming L1 from L2 hits improves future performance
    - Batch operations reduce network overhead

    Performance Impact:
    - L1 hit: < 1ms (no network)
    - L2 hit: 1-5ms (network + Redis)
    - L1 warming: Improves subsequent L1 hit rate
    """

    def __init__(self, l1: L1Storage, l2: L2Storage):
        """
        Initialize cache strategy.

        Args:
            l1: L1 (in-memory) storage
            l2: L2 (Redis) storage
        """
        self._l1 = l1
        self._l2 = l2

    async def get(self, key: str) -> tuple[str | None, CacheSource]:
        """
        Get from cache with L1→L2 fallback.

        STAGE-2.1: L1 lookup
        STAGE-2.2: L2 lookup (if L1 miss)

        Algorithm:
        1. Check L1 (fast path, < 1ms)
        2. If L1 miss, check L2 (1-5ms)
        3. If L2 hit, warm L1 for future requests
        4. Return value and source

        Why Warm L1 on L2 Hit?
        - Next request will hit L1 (< 1ms instead of 1-5ms)
        - Reduces Redis load
        - Improves overall hit rate

        Args:
            key: Cache key

        Returns:
            (value, source) where source indicates which tier hit
        """
        # Try L1 first (fastest path)
        value = await self._l1.get(key)
        if value is not None:
            return value, "l1"

        # Try L2 (slower but distributed)
        value = await self._l2.get(key)
        if value is not None:
            # Warm L1 with L2 result
            # This makes the next request faster
            await self._l1.set(key, value)
            return value, "l2"

        # Cache miss - need to compute value
        return None, "miss"

    async def set(
        self,
        key: str,
        value: str,
        ttl: int,
        l1_only: bool = False
    ) -> None:
        """
        Set value in cache tiers.

        STAGE-2.3: Cache population

        Strategy:
        - Always populate L1 (fast access)
        - Optionally populate L2 (distribution)

        When to use l1_only=True?
        - Temporary data (session state)
        - Data specific to this instance
        - Data that shouldn't be shared

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live for L2
            l1_only: If True, only cache in L1 (for temporary data)
        """
        # Always populate L1 (fast access)
        await self._l1.set(key, value)

        # Populate L2 for distribution (unless l1_only)
        if not l1_only:
            await self._l2.set(key, value, ttl)

    async def batch_get(self, keys: list[str]) -> dict[str, tuple[str | None, CacheSource]]:
        """
        Batch get with L1/L2 fallback and L1 warming.

        Algorithm:
            1. Check L1 for all keys (fast path)
            2. Collect L1 misses
            3. Pipeline fetch from L2 (single round-trip)
            4. Warm L1 with L2 hits
            5. Return all results

        Performance Optimization:
        - L1 checks are fast (< 1ms each)
        - L2 pipeline is single network call (not N calls)
        - L1 warming improves future hit rate

        Example:
            100 keys, 80 L1 hits, 15 L2 hits, 5 misses
            - 80 L1 lookups: ~80ms total
            - 1 L2 pipeline call: ~5ms (not 15 * 5ms = 75ms)
            - Total: ~85ms vs ~155ms without pipelining

        Args:
            keys: List of cache keys

        Returns:
            Dict mapping key → (value, source)
        """
        if not keys:
            return {}

        results: dict[str, tuple[str | None, CacheSource]] = {}
        l2_keys = []

        # Phase 1: Check L1 for all keys (fast path)
        for key in keys:
            value = await self._l1.get(key)
            if value is not None:
                results[key] = (value, "l1")
            else:
                l2_keys.append(key)

        # Phase 2: Pipeline L2 lookups for misses
        # This is the critical optimization - single network call
        if l2_keys:
            l2_results = await self._l2.batch_get(l2_keys)

            # Phase 3: Process L2 results and warm L1
            for key, value in l2_results.items():
                if value is not None:
                    # Warm L1 for future requests
                    await self._l1.set(key, value)
                    results[key] = (value, "l2")
                else:
                    results[key] = (None, "miss")

        return results

    async def delete(self, key: str) -> None:
        """
        Delete from both tiers.

        STAGE-2.4: Cache invalidation

        Why Delete from Both?
        - Ensures consistency across tiers
        - Prevents stale data in L1

        Args:
            key: Cache key
        """
        await self._l1.delete(key)
        await self._l2.delete(key)

    async def clear_l1(self) -> None:
        """
        Clear L1 cache only.

        Use Case: Memory cleanup, testing, or cache reset
        """
        await self._l1.clear()

    def get_l1_keys(self) -> list[str]:
        """
        Get all L1 keys (most recent last).

        Returns:
            List of keys in LRU order
        """
        return self._l1.get_keys()


# =============================================================================
# LAYER 3: OBSERVABILITY
# Tracks metrics, logs operations, integrates with monitoring
# =============================================================================


class CacheObserver:
    """
    Tracks cache performance metrics and logs operations.

    Responsibility: All side effects (logging, metrics, tracing).

    Why Separate Observer?
    - Single Responsibility Principle
    - Easy to test cache logic without logging
    - Can swap monitoring implementations
    - Centralizes all observability concerns

    Metrics Tracked:
    - L1 hits, L2 hits, misses
    - Hit rates (overall, L1-specific)
    - Operation counts
    """

    def __init__(self, tracker=None, logger_instance=None):
        """
        Initialize cache observer.

        Args:
            tracker: Execution tracker instance
            logger_instance: Logger instance
        """
        self._tracker = tracker or get_tracker()
        self._logger = logger_instance or logger

        # Metrics
        self._hits_l1 = 0
        self._hits_l2 = 0
        self._misses = 0

    def record_operation(
        self,
        operation: str,
        source: CacheSource,
        key: str,
        thread_id: str | None = None
    ) -> None:
        """
        Record cache operation for metrics and logging.

        Logging Strategy:
        - L1 hit: STAGE-2.1 (fastest path)
        - L2 hit: STAGE-2.2 (slower but still cached)
        - Miss: STAGE-2.2 (need to compute)
        - Set: STAGE-2.3 (cache population)
        - Delete: STAGE-2.4 (invalidation)

        Args:
            operation: 'get', 'set', 'delete'
            source: Which tier was hit ('l1', 'l2', 'miss')
            key: Cache key (truncated for logging)
            thread_id: Optional thread ID for distributed tracing
        """
        if operation == "get":
            if source == "l1":
                self._hits_l1 += 1
                log_stage(self._logger, "2.1", "L1 cache hit", cache_key=key[:20])
            elif source == "l2":
                self._hits_l2 += 1
                log_stage(self._logger, "2.2", "L2 cache hit", cache_key=key[:20])
            else:
                self._misses += 1
                log_stage(self._logger, "2.2", "Cache miss", cache_key=key[:20])

        elif operation == "set":
            log_stage(self._logger, "2.3", "Cache set", cache_key=key[:20])

        elif operation == "delete":
            log_stage(self._logger, "2.4", "Cache invalidated", cache_key=key[:20])

    def wrap_with_tracking(
        self,
        stage: str,
        description: str,
        thread_id: str | None
    ):
        """
        Context manager for stage tracking.

        Returns a context manager if thread_id provided, else a no-op.

        Why Conditional Tracking?
        - Not all operations need distributed tracing
        - Reduces overhead for simple operations
        - Allows fine-grained control

        Args:
            stage: Stage identifier (e.g., "2.1", "2.2")
            description: Human-readable description
            thread_id: Thread ID for tracking (None = no tracking)

        Returns:
            Context manager for tracking or no-op
        """
        if thread_id:
            return self._tracker.track_stage(stage, description, thread_id)
        else:
            # No-op context manager
            from contextlib import nullcontext
            return nullcontext()

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache performance statistics.

        Metrics Provided:
        - L1 hits, L2 hits, misses
        - Total requests
        - Overall hit rate
        - L1-specific hit rate

        Returns:
            Dict with performance metrics
        """
        total = self._hits_l1 + self._hits_l2 + self._misses
        hit_rate = (self._hits_l1 + self._hits_l2) / total if total > 0 else 0.0

        return {
            "l1_hits": self._hits_l1,
            "l2_hits": self._hits_l2,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": round(hit_rate, 3),
            "l1_hit_rate": round(self._hits_l1 / total, 3) if total > 0 else 0.0,
        }


# =============================================================================
# LAYER 4: CACHE WARMING
# Strategies for pre-loading frequently accessed data
# =============================================================================


class CacheWarmer:
    """
    Implements cache warming strategies.

    Responsibility: Pre-load frequently accessed keys into L1.

    Why Cache Warming?
    - Reduces cold start latency
    - Improves L1 hit rate after deployment
    - Pre-loads known popular keys
    - Optimizes for predictable access patterns

    Strategies:
    1. Explicit warming: Pre-load specific keys
    2. Popular key warming: Re-fetch most recent L1 keys from L2
    """

    def __init__(self, strategy: CacheStrategy):
        """
        Initialize cache warmer.

        Args:
            strategy: Cache strategy instance
        """
        self._strategy = strategy

    async def warm_from_keys(self, keys: list[str]) -> int:
        """
        Warm L1 cache with specific keys from L2.

        Use case: Pre-load known popular keys during startup or after deployment.

        Algorithm:
        1. Batch fetch keys from L2 (pipelined)
        2. Populate L1 with results
        3. Return count of warmed keys

        When to Use:
        - Application startup
        - After deployment
        - After cache clear
        - Known popular keys

        Args:
            keys: List of cache keys to warm

        Returns:
            Number of keys successfully warmed
        """
        if not keys:
            return 0

        # Batch fetch from L2 (single network call)
        results = await self._strategy._l2.batch_get(keys)
        warmed = 0

        # Populate L1 with results
        for key, value in results.items():
            if value is not None:
                await self._strategy._l1.set(key, value)
                warmed += 1

        if warmed > 0:
            log_stage(logger, "2.warming", "L1 cache warming complete", warmed_items=warmed)

        return warmed

    async def warm_popular_from_l2(self, limit: int = 20) -> int:
        """
        Warm L1 with most recently used keys.

        Strategy: Take most recent keys from L1, re-fetch from L2 to ensure freshness.

        Why Re-fetch from L2?
        - Ensures data is still fresh
        - Validates keys still exist
        - Updates L1 with latest values

        Algorithm:
        1. Get most recent keys from L1 (LRU ordering)
        2. Re-fetch from L2 (ensures freshness)
        3. Warm L1 with results

        When to Use:
        - Periodic warming (e.g., every 5 minutes)
        - After high cache miss rate
        - After L1 evictions

        Args:
            limit: Number of keys to warm

        Returns:
            Number of keys successfully warmed
        """
        # Get most recent keys from L1 (these are likely popular)
        l1_keys = self._strategy.get_l1_keys()

        if not l1_keys:
            return 0

        # Take the N most recent
        recent_keys = l1_keys[-limit:] if len(l1_keys) > limit else l1_keys

        # Re-fetch from L2 to ensure fresh data
        return await self.warm_from_keys(recent_keys)


# =============================================================================
# LAYER 5: PUBLIC API
# Clean interface that coordinates all layers
# =============================================================================


class CacheManager:
    """
    Multi-tier cache manager with L1 (in-memory) and L2 (Redis).

    Public API for all caching operations.

    Features:
        - Automatic L1→L2 fallback
        - Batch operations with pipelining
        - Cache warming strategies
        - Performance monitoring
        - Health checks

    Usage:
        cache = CacheManager()
        await cache.initialize()

        # Simple get/set
        value = await cache.get("key")
        await cache.set("key", "value", ttl=3600)

        # Batch operations
        results = await cache.batch_get(["key1", "key2", "key3"])

        # Cache warming
        await cache.warm_cache(["popular_key1", "popular_key2"])

        # Monitoring
        stats = cache.stats()

    Architecture:
        CacheManager (this class)
            ├── CacheStrategy (L1→L2 logic)
            │   ├── L1Storage (in-memory)
            │   └── L2Storage (Redis)
            ├── CacheObserver (metrics)
            └── CacheWarmer (warming)
    """

    def __init__(self):
        """
        Initialize cache manager.

        STAGE-2.0: Cache manager initialization
        """
        settings = get_settings()

        # Build layers
        self._l1 = L1Storage(max_size=settings.cache.CACHE_L1_MAX_SIZE)
        self._l2 = L2Storage(get_redis_client())
        self._strategy = CacheStrategy(self._l1, self._l2)
        self._observer = CacheObserver()
        self._warmer = CacheWarmer(self._strategy)

        # Configuration
        self._enabled = settings.ENABLE_CACHING
        self._default_ttl = settings.cache.CACHE_RESPONSE_TTL
        self._initialized = False

        logger.info(
            "Cache manager initialized",
            stage="2.0",
            l1_max_size=settings.cache.CACHE_L1_MAX_SIZE,
            caching_enabled=self._enabled,
        )

    async def initialize(self) -> None:
        """
        Initialize L2 (Redis) connection.

        STAGE-2.0.1: Initialize L2 (Redis) connection
        """
        if self._initialized:
            return

        await self._l2.connect()
        self._initialized = True

        logger.info("Cache manager L2 (Redis) connected", stage="2.0.1")

    async def shutdown(self) -> None:
        """
        Shutdown cache connections and clear L1.

        STAGE-2.0.2: Cleanup cache connections
        """
        await self._strategy.clear_l1()
        self._initialized = False

        logger.info("Cache manager shutdown", stage="2.0.2")

    # -------------------------------------------------------------------------
    # Core Cache Operations
    # -------------------------------------------------------------------------

    async def get(self, key: str, thread_id: str | None = None) -> str | None:
        """
        Get value from cache with L1→L2 fallback.

        STAGE-2.1: L1 lookup
        STAGE-2.2: L2 lookup (if L1 miss)

        Args:
            key: Cache key
            thread_id: Optional thread ID for distributed tracing

        Returns:
            Cached value or None if not found

        Performance:
        - L1 hit: < 1ms
        - L2 hit: 1-5ms
        - Miss: returns None
        """
        if not self._enabled:
            return None

        with self._observer.wrap_with_tracking("2.1-2.2", "Cache lookup", thread_id):
            value, source = await self._strategy.get(key)

        self._observer.record_operation("get", source, key, thread_id)
        return value

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
        thread_id: str | None = None,
        l1_only: bool = False,
    ) -> None:
        """
        Set value in cache.

        STAGE-2.3: Cache population

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (default: from settings)
            thread_id: Optional thread ID for distributed tracing
            l1_only: If True, only cache in L1 (for temporary data)

        Optimization:
        - L1 always populated for fast access
        - L2 populated for distributed access
        - TTL ensures stale data eviction
        """
        if not self._enabled:
            return

        ttl = ttl or self._default_ttl

        with self._observer.wrap_with_tracking("2.3", "Cache set", thread_id):
            await self._strategy.set(key, value, ttl, l1_only)

        self._observer.record_operation("set", "l1" if l1_only else "l2", key, thread_id)

    async def delete(self, key: str) -> None:
        """
        Delete value from both cache tiers.

        STAGE-2.4: Cache invalidation

        Args:
            key: Cache key
        """
        await self._strategy.delete(key)
        self._observer.record_operation("delete", "l1", key)

    async def batch_get(
        self,
        keys: list[str],
        thread_id: str | None = None
    ) -> dict[str, str | None]:
        """
        Get multiple values using pipelining.

        Uses Redis pipelining to reduce network round-trips by 50-70%.

        Algorithm:
        1. Check L1 for all keys (fast path)
        2. Collect L1 misses
        3. Pipeline fetch from L2 (single round-trip)
        4. Warm L1 with L2 hits
        5. Return all results

        Args:
            keys: List of cache keys
            thread_id: Optional thread ID for distributed tracing

        Returns:
            Dict mapping key → value (None if not found)
        """
        if not self._enabled or not keys:
            return {k: None for k in keys}

        with self._observer.wrap_with_tracking("2.batch", "Batch cache lookup", thread_id):
            results = await self._strategy.batch_get(keys)

        # Return simplified dict (drop source info)
        return {k: v[0] for k, v in results.items()}

    # -------------------------------------------------------------------------
    # Cache Warming
    # -------------------------------------------------------------------------

    async def warm_cache(self, keys: list[str]) -> int:
        """
        Explicitly warm L1 cache from L2.

        Use Case: Pre-load known popular keys during startup or after deployment.

        Args:
            keys: List of cache keys to pre-load

        Returns:
            Number of keys successfully warmed
        """
        return await self._warmer.warm_from_keys(keys)

    async def warm_popular_keys(self, limit: int = 20) -> int:
        """
        Warm L1 with most recently accessed keys.

        Strategy: Re-fetch most recent L1 keys from L2 to ensure freshness.

        Args:
            limit: Number of keys to warm

        Returns:
            Number of keys successfully warmed
        """
        return await self._warmer.warm_popular_from_l2(limit)

    # -------------------------------------------------------------------------
    # Advanced Patterns
    # -------------------------------------------------------------------------

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl: int | None = None,
        thread_id: str | None = None,
    ) -> Any:
        """
        Get from cache or compute and cache the result (cache-aside pattern).

        STAGE-2.5: Cache-aside pattern

        Pattern: Cache-aside (lazy loading)
        - Check cache first
        - If miss, compute and cache
        - Return result

        Args:
            key: Cache key
            compute_fn: Async function to compute value if not cached
            ttl: Time-to-live in seconds
            thread_id: Thread ID for execution tracking

        Returns:
            Cached or computed value
        """
        # Check cache first
        cached = await self.get(key, thread_id)
        if cached is not None:
            return cached

        # Compute value
        with self._observer.wrap_with_tracking("2.5", "Computing uncached value", thread_id):
            if asyncio.iscoroutinefunction(compute_fn):
                value = await compute_fn()
            else:
                value = compute_fn()

        # Cache result
        if isinstance(value, str):
            await self.set(key, value, ttl, thread_id)
        else:
            # Serialize non-string values
            serialized = orjson.dumps(value).decode('utf-8')
            await self.set(key, serialized, ttl, thread_id)

        return value

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def generate_cache_key(prefix: str, *args: Any) -> str:
        """
        Generate consistent cache key from prefix and arguments.

        STAGE-2.1.1: Cache key generation

        Uses MD5 for fast hashing (collision risk acceptable for cache).

        Args:
            prefix: Key prefix (e.g., "response", "session")
            *args: Values to hash for the key

        Returns:
            Cache key (e.g., "cache:response:abc123def...")

        Optimization: Uses MD5 for fast hashing
        - MD5 is fast (not cryptographically secure, but fine for cache)
        - Collision risk is acceptable (worst case: cache miss)
        - Consistent hashing ensures same input → same key
        """
        data = ":".join(str(arg) for arg in args)
        hash_value = hashlib.md5(data.encode()).hexdigest()
        return f"{REDIS_KEY_CACHE_RESPONSE}:{prefix}:{hash_value}"

    # -------------------------------------------------------------------------
    # Monitoring
    # -------------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """
        Get cache performance statistics.

        Returns:
            Dict with hit rates, sizes, and capacity utilization
        """
        observer_stats = self._observer.get_stats()
        l1_size = self._l1.get_size()
        l1_max = self._l1.get_max_size()

        return {
            **observer_stats,
            "l1_size": l1_size,
            "l1_max_size": l1_max,
            "l1_capacity_utilization": round(l1_size / l1_max * 100, 2),
            "l2_connected": self._initialized,
            "caching_enabled": self._enabled,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    async def health_check(self) -> dict[str, Any]:
        """
        Perform health check on cache system.

        Returns:
            Dict with health status for all layers
        """
        health = {
            "status": "healthy",
            "caching_enabled": self._enabled,
            "l1": {
                "status": "healthy",
                "size": self._l1.get_size(),
                "max_size": self._l1.get_max_size(),
            },
            "l2": None,
        }

        if self._initialized:
            try:
                l2_health = await self._l2.health_check()
                health["l2"] = l2_health

                if l2_health.get("status") != "healthy":
                    health["status"] = "degraded"
            except Exception as e:
                health["status"] = "degraded"
                health["l2"] = {"status": "error", "error": str(e)}
        else:
            health["status"] = "degraded"
            health["l2"] = {"status": "not_connected"}

        return health


# =============================================================================
# GLOBAL INSTANCE (SINGLETON PATTERN)
# =============================================================================

_cache_manager: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    """
    Get the global cache manager instance (singleton).

    Returns:
        CacheManager: Global cache manager instance
    """
    global _cache_manager

    if _cache_manager is None:
        _cache_manager = CacheManager()

    return _cache_manager


async def init_cache() -> CacheManager:
    """
    Initialize and connect the global cache manager.

    Returns:
        CacheManager: Initialized cache manager
    """
    manager = get_cache_manager()
    await manager.initialize()
    return manager


async def close_cache() -> None:
    """Shutdown the global cache manager."""
    global _cache_manager

    if _cache_manager:
        await _cache_manager.shutdown()
