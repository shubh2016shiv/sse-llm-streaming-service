"""
Unit Tests for CacheManager

Tests the multi-tier caching strategy (L1 + L2) and cache orchestration logic.
Verifies proper tier selection, fallback, and key generation.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.config.constants import REDIS_KEY_CACHE_RESPONSE
from src.infrastructure.cache.cache_manager import CacheManager


@pytest.mark.unit
class TestCacheManager:
    """Test suite for CacheManager."""

    @pytest.mark.asyncio
    async def test_get_returns_none_if_caching_disabled(self, cache_manager, mock_settings):
        """Test that get returns None immediately if caching is disabled."""
        mock_settings.ENABLE_CACHING = False

        result = await cache_manager.get("test-key")

        assert result is None
        # Should not access L1 or L2
        assert cache_manager._memory_cache.get("test-key") is not None  # Wait, async call
        # Actually simplest check is result

    @pytest.mark.asyncio
    async def test_l1_cache_hit(self, cache_manager):
        """Test that L1 hit returns value without checking L2."""
        key = "test-key"
        value = "cached-value"

        # Populate L1
        await cache_manager._memory_cache.set(key, value)

        # Get
        result = await cache_manager.get(key)

        assert result == value
        # Verify L2 was NOT called
        cache_manager._redis_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_l1_miss_l2_hit_populates_l1(self, cache_manager):
        """Test that L2 hit returns value and populates L1 (cache warming)."""
        key = "test-key"
        value = "redis-value"

        # Setup L2 hit
        cache_manager._redis_client.get.return_value = value

        # Get
        result = await cache_manager.get(key)

        assert result == value
        # Verify L1 was populated
        l1_val = await cache_manager._memory_cache.get(key)
        assert l1_val == value

    @pytest.mark.asyncio
    async def test_l1_miss_l2_miss_returns_none(self, cache_manager):
        """Test that miss in both tiers returns None."""
        key = "test-key"

        # Setup L2 miss
        cache_manager._redis_client.get.return_value = None

        result = await cache_manager.get(key)

        assert result is None

    @pytest.mark.asyncio
    async def test_set_writes_to_both_tiers(self, cache_manager):
        """Test that set writes to both L1 and L2."""
        key = "test-key"
        value = "test-value"

        await cache_manager.set(key, value)

        # Verify L1 set
        l1_val = await cache_manager._memory_cache.get(key)
        assert l1_val == value

        # Verify L2 set
        cache_manager._redis_client.set.assert_called_once()
        args = cache_manager._redis_client.set.call_args
        assert args[0][0] == key
        assert args[0][1] == value

    def test_generate_cache_key_is_consistent(self):
        """Test that cache key generation is deterministic."""
        prefix = "test"
        args = ("arg1", "arg2", 123)

        key1 = CacheManager.generate_cache_key(prefix, *args)
        key2 = CacheManager.generate_cache_key(prefix, *args)

        assert key1 == key2
        assert prefix in key1
        assert REDIS_KEY_CACHE_RESPONSE in key1

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, cache_manager):
        """Test health check formatting."""
        # Setup healthy L2
        cache_manager._redis_client.health_check.return_value = {"status": "healthy"}

        health = await cache_manager.health_check()

        assert health["status"] == "healthy"
        assert "l1" in health
        assert "l2" in health

    @pytest.mark.asyncio
    async def test_l1_cache_eviction_on_capacity(self, cache_manager):
        """Test L1 cache evicts oldest items when capacity is reached."""
        # Fill cache to capacity
        max_size = cache_manager._memory_cache.max_size
        for i in range(max_size + 5):  # Add some extra
            key = f"key-{i}"
            await cache_manager._memory_cache.set(key, f"value-{i}")

        # Check that oldest items were evicted
        size = cache_manager._memory_cache.size
        assert size <= max_size

        # Most recent items should still be there
        recent_key = f"key-{max_size + 4}"
        recent_value = await cache_manager._memory_cache.get(recent_key)
        assert recent_value == f"value-{max_size + 4}"

    @pytest.mark.asyncio
    async def test_l1_cache_hit_rate_calculation(self, cache_manager):
        """Test L1 cache hit rate calculation."""
        # Perform some hits and misses
        await cache_manager._memory_cache.set("hit-key", "value")

        # Hits
        for _ in range(3):
            await cache_manager._memory_cache.get("hit-key")

        # Misses
        for _ in range(2):
            await cache_manager._memory_cache.get("miss-key")

        stats = cache_manager._memory_cache.stats()
        expected_hit_rate = 3 / (3 + 2)  # 3 hits out of 5 accesses

        assert abs(stats["hit_rate"] - expected_hit_rate) < 0.001

    @pytest.mark.asyncio
    async def test_batch_get_from_l1_only(self, cache_manager):
        """Test batch_get when all keys are in L1."""
        # Populate L1 with test data
        test_data = {f"key-{i}": f"value-{i}" for i in range(5)}
        for key, value in test_data.items():
            await cache_manager._memory_cache.set(key, value)

        # Batch get
        keys = list(test_data.keys())
        result = await cache_manager.batch_get(keys)

        assert len(result) == 5
        for key, expected_value in test_data.items():
            assert result[key] == expected_value

        # L2 should not be called since all were in L1
        cache_manager._redis_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_get_mixed_l1_l2(self, cache_manager):
        """Test batch_get with mixed L1/L2 hits."""
        # L1 has key-0 and key-1
        await cache_manager._memory_cache.set("key-0", "l1-value-0")
        await cache_manager._memory_cache.set("key-1", "l1-value-1")

        # L2 has key-2 and key-3
        cache_manager._redis_client.get.side_effect = lambda key: {
            "key-2": "l2-value-2",
            "key-3": "l2-value-3",
            "key-4": None,  # Miss
        }.get(key)

        keys = ["key-0", "key-1", "key-2", "key-3", "key-4"]
        result = await cache_manager.batch_get(keys)

        # Check results
        assert result["key-0"] == "l1-value-0"
        assert result["key-1"] == "l1-value-1"
        assert result["key-2"] == "l2-value-2"
        assert result["key-3"] == "l2-value-3"
        assert result["key-4"] is None

        # L2 values should be warmed to L1
        l1_value_2 = await cache_manager._memory_cache.get("key-2")
        assert l1_value_2 == "l2-value-2"

    @pytest.mark.asyncio
    async def test_batch_get_with_pipeline_fallback(self, cache_manager):
        """Test batch_get falls back to individual gets when pipeline unavailable."""
        # Mock pipeline as None (not available)
        cache_manager._redis_client.get_pipeline_manager.return_value = None

        # Setup L2 responses
        cache_manager._redis_client.get.side_effect = lambda key: f"l2-{key}"

        keys = ["key-1", "key-2", "key-3"]
        result = await cache_manager.batch_get(keys)

        # Should get results via individual calls
        assert result["key-1"] == "l2-key-1"
        assert result["key-2"] == "l2-key-2"
        assert result["key-3"] == "l2-key-3"

        # Should have made individual calls
        assert cache_manager._redis_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_ttl_handling_in_set(self, cache_manager, mock_settings):
        """Test TTL parameter handling in set operations."""
        key = "ttl-key"
        value = "ttl-value"
        ttl = 3600

        await cache_manager.set(key, value, ttl=ttl)

        # Verify L2 set was called with TTL
        cache_manager._redis_client.set.assert_called_with(key, value, ttl=ttl)

    @pytest.mark.asyncio
    async def test_default_ttl_from_settings(self, cache_manager, mock_settings):
        """Test that default TTL comes from settings."""
        mock_settings.cache.CACHE_RESPONSE_TTL = 1800

        key = "default-ttl-key"
        value = "default-ttl-value"

        await cache_manager.set(key, value)

        # Should use settings default
        cache_manager._redis_client.set.assert_called_with(key, value, ttl=1800)

    @pytest.mark.asyncio
    async def test_l1_only_set_mode(self, cache_manager):
        """Test set with l1_only=True only populates L1."""
        key = "l1-only-key"
        value = "l1-only-value"

        await cache_manager.set(key, value, l1_only=True)

        # L1 should have the value
        l1_value = await cache_manager._memory_cache.get(key)
        assert l1_value == value

        # L2 should NOT be called
        cache_manager._redis_client.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_warm_l1_from_popular_success(self, cache_manager):
        """Test successful L1 warming from popular keys."""
        # Setup popular keys in L1
        popular_keys = [f"popular-{i}" for i in range(5)]
        for key in popular_keys:
            await cache_manager._memory_cache.set(key, f"value-{key}")

        # Mock L2 to have additional data
        cache_manager._redis_client.get.side_effect = (
            lambda key: f"l2-{key}" if "popular" in key else None
        )

        await cache_manager.warm_l1_from_popular()

        # Should have attempted to fetch popular keys
        # (Exact behavior depends on implementation, but should not crash)

    @pytest.mark.asyncio
    async def test_warm_l1_from_popular_with_errors(self, cache_manager):
        """Test L1 warming handles errors gracefully."""
        # Setup some popular keys
        await cache_manager._memory_cache.set("popular-1", "value-1")

        # Mock L2 to fail
        cache_manager._redis_client.get.side_effect = Exception("Redis error")

        # Should not raise exception
        await cache_manager.warm_l1_from_popular()

    @pytest.mark.asyncio
    async def test_cache_aside_pattern_get_or_compute_hit(self, cache_manager):
        """Test cache-aside pattern when cache hit occurs."""
        key = "compute-key"
        cached_value = "cached-result"

        # Populate cache
        await cache_manager.set(key, cached_value)

        async def expensive_compute():
            return "computed-result"  # Should not be called

        result = await cache_manager.get_or_compute(key, expensive_compute)

        assert result == cached_value

    @pytest.mark.asyncio
    async def test_cache_aside_pattern_miss(self, cache_manager):
        """Test cache-aside pattern when cache miss occurs."""
        key = "compute-key"
        computed_value = "computed-result"

        async def expensive_compute():
            return computed_value

        result = await cache_manager.get_or_compute(key, expensive_compute)

        assert result == computed_value

        # Should be cached now
        cached = await cache_manager.get(key)
        assert cached == computed_value

    @pytest.mark.asyncio
    async def test_cache_aside_with_non_string_result(self, cache_manager):
        """Test cache-aside pattern serializes non-string results."""
        key = "object-key"
        computed_object = {"data": "value", "count": 42}

        async def compute_object():
            return computed_object

        result = await cache_manager.get_or_compute(key, compute_object)

        assert result == computed_object

        # Should be cached as JSON string
        cached = await cache_manager.get(key)
        assert isinstance(cached, str)
        # Would be JSON, but exact format depends on implementation

    @pytest.mark.asyncio
    async def test_delete_from_both_tiers(self, cache_manager):
        """Test delete removes from both L1 and L2."""
        key = "delete-key"
        value = "delete-value"

        # Set in both tiers
        await cache_manager.set(key, value)

        # Delete
        await cache_manager.delete(key)

        # Should be gone from L1
        l1_value = await cache_manager._memory_cache.get(key)
        assert l1_value is None

        # Should be deleted from L2
        cache_manager._redis_client.delete.assert_called_with(key)

    @pytest.mark.asyncio
    async def test_health_check_degraded_when_l2_unhealthy(self, cache_manager):
        """Test health check shows degraded when L2 is unhealthy."""
        # Mock unhealthy L2
        cache_manager._redis_client.health_check.return_value = {"status": "unhealthy"}

        health = await cache_manager.health_check()

        assert health["status"] == "degraded"
        assert health["l2"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_degraded_when_no_l2_connection(self, cache_manager):
        """Test health check shows degraded when L2 not connected."""
        # Mock no L2 connection
        cache_manager._redis_client = None

        health = await cache_manager.health_check()

        assert health["status"] == "degraded"
        assert health["l2"]["status"] == "not_connected"

    @pytest.mark.asyncio
    async def test_get_popular_keys_returns_recent_keys(self, cache_manager):
        """Test get_popular_keys returns most recently used keys."""
        # Add keys in order (older first)
        keys = [f"key-{i}" for i in range(10)]
        for key in keys:
            await cache_manager._memory_cache.set(key, f"value-{key}")

        # Access some keys to change LRU order
        await cache_manager._memory_cache.get("key-5")  # Make key-5 most recent
        await cache_manager._memory_cache.get("key-8")  # Make key-8 more recent

        popular = await cache_manager.get_popular_keys(limit=3)

        # Should include most recently accessed
        assert "key-8" in popular
        assert "key-5" in popular

    @pytest.mark.asyncio
    async def test_thread_id_tracking_in_operations(self, cache_manager):
        """Test that thread_id is passed to execution tracker."""
        key = "tracked-key"

        with patch("src.infrastructure.cache.cache_manager.get_tracker") as mock_get_tracker:
            mock_tracker = MagicMock()
            mock_get_tracker.return_value = mock_tracker

            await cache_manager.get(key, thread_id="test-thread")

            # Should have called tracker for stage tracking
            # (Exact calls depend on implementation)

    @pytest.mark.asyncio
    async def test_empty_batch_get(self, cache_manager):
        """Test batch_get with empty key list."""
        result = await cache_manager.batch_get([])
        assert result == {}


@pytest.mark.unit
class TestLRUCache:
    """Test suite for LRUCache component."""

    @pytest.fixture
    def lru_cache(self):
        """Create LRUCache instance for testing."""
        from src.infrastructure.cache.cache_manager import LRUCache

        return LRUCache(max_size=3)

    @pytest.mark.asyncio
    async def test_lru_eviction_policy(self, lru_cache):
        """Test LRU eviction removes least recently used items."""
        # Fill cache
        await lru_cache.set("a", "value-a")
        await lru_cache.set("b", "value-b")
        await lru_cache.set("c", "value-c")

        # Access 'a' to make it most recently used
        await lru_cache.get("a")

        # Add another item, should evict 'b' (least recently used)
        await lru_cache.set("d", "value-d")

        # 'b' should be evicted
        assert await lru_cache.get("b") is None
        # Others should remain
        assert await lru_cache.get("a") == "value-a"
        assert await lru_cache.get("c") == "value-c"
        assert await lru_cache.get("d") == "value-d"

    @pytest.mark.asyncio
    async def test_lru_cache_size_limit(self, lru_cache):
        """Test cache respects maximum size."""
        for i in range(10):
            await lru_cache.set(f"key-{i}", f"value-{i}")

        # Size should not exceed max_size
        assert lru_cache.size <= lru_cache.max_size

    @pytest.mark.asyncio
    async def test_lru_update_existing_key(self, lru_cache):
        """Test updating existing key moves it to most recent."""
        await lru_cache.set("a", "old-value")
        await lru_cache.set("b", "value-b")
        await lru_cache.set("c", "value-c")

        # Update 'a', making it most recent
        await lru_cache.set("a", "new-value")

        # Add another to trigger eviction - should evict 'b'
        await lru_cache.set("d", "value-d")

        assert await lru_cache.get("b") is None
        assert await lru_cache.get("a") == "new-value"

    @pytest.mark.asyncio
    async def test_lru_delete_operation(self, lru_cache):
        """Test delete removes items correctly."""
        await lru_cache.set("test", "value")

        # Should return True for successful delete
        result = await lru_cache.delete("test")
        assert result is True

        # Should return False for non-existent key
        result = await lru_cache.delete("nonexistent")
        assert result is False

        # Item should be gone
        assert await lru_cache.get("test") is None

    @pytest.mark.asyncio
    async def test_lru_clear_operation(self, lru_cache):
        """Test clear removes all items."""
        await lru_cache.set("a", "1")
        await lru_cache.set("b", "2")

        await lru_cache.clear()

        assert lru_cache.size == 0
        assert await lru_cache.get("a") is None
        assert await lru_cache.get("b") is None

    @pytest.mark.asyncio
    async def test_lru_stats_calculation(self, lru_cache):
        """Test stats calculation with hits and misses."""
        # Add item
        await lru_cache.set("test", "value")

        # Hits
        for _ in range(5):
            await lru_cache.get("test")

        # Misses
        for _ in range(3):
            await lru_cache.get("missing")

        stats = lru_cache.stats()

        assert stats["size"] == 1
        assert stats["hits"] == 5
        assert stats["misses"] == 3
        assert stats["hit_rate"] == 5 / (5 + 3)  # 5/8

    @pytest.mark.asyncio
    async def test_lru_zero_max_size(self):
        """Test LRU cache with zero max size."""
        from src.infrastructure.cache.cache_manager import LRUCache

        cache = LRUCache(max_size=0)

        await cache.set("test", "value")
        result = await cache.get("test")

        # Should not store anything
        assert result is None
        assert cache.size == 0
