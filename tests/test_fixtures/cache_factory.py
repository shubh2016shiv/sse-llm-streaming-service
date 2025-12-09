"""
Cache Test Factory

Creates cache managers and Redis clients with various configurations for testing.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock


class CacheTestFactory:
    """Factory for creating cache test objects."""

    @staticmethod
    def mock_cache_manager(hit_rate: float = 0.0, l1_size: int = 1000) -> MagicMock:
        """Create a mock cache manager with controllable behavior."""
        from src.infrastructure.cache.cache_manager import CacheManager

        cache = MagicMock(spec=CacheManager)
        cache.get = AsyncMock()
        cache.set = AsyncMock(return_value=True)
        cache.delete = AsyncMock(return_value=True)

        # Configure hit/miss behavior
        cache.get.side_effect = (
            lambda key, thread_id=None: "cached_value"
            if hash(key) % 100 < (hit_rate * 100)
            else None
        )

        # Stats with configurable hit rate
        cache.stats.return_value = {
            "l1": {
                "size": l1_size,
                "max_size": 1000,
                "hits": int(hit_rate * 1000),
                "misses": int((1 - hit_rate) * 1000),
                "hit_rate": hit_rate,
            },
            "l2_connected": True,
            "timestamp": "2024-01-01T00:00:00Z",
        }

        cache.health_check = AsyncMock(return_value={"status": "healthy"})
        return cache

    @staticmethod
    def redis_client_with_data(initial_data: dict[str, Any] | None = None) -> AsyncMock:
        """Create a Redis client mock with initial data."""
        client = AsyncMock()
        client.connect = AsyncMock()
        client.data = initial_data or {}

        async def mock_get(key):
            return client.data.get(key)

        async def mock_set(key, value, ttl=None):
            client.data[key] = value
            if ttl:
                # Could implement TTL logic here if needed
                pass

        async def mock_delete(key):
            if key in client.data:
                del client.data[key]

        client.get = mock_get
        client.set = mock_set
        client.delete = mock_delete
        client.incr = AsyncMock(return_value=1)
        client.health_check = AsyncMock(return_value={"status": "healthy"})

        return client

    @staticmethod
    def failing_redis_client(error: Exception = None) -> AsyncMock:
        """Create a Redis client that always fails."""
        if error is None:
            error = Exception("Redis connection failed")

        client = AsyncMock()
        client.connect = AsyncMock(side_effect=error)
        client.get = AsyncMock(side_effect=error)
        client.set = AsyncMock(side_effect=error)
        client.health_check = AsyncMock(return_value={"status": "unhealthy", "error": str(error)})

        return client

    @staticmethod
    def slow_redis_client(delay: float = 1.0) -> AsyncMock:
        """Create a Redis client with artificial delays."""
        import asyncio

        client = AsyncMock()
        client.connect = AsyncMock()

        async def delayed_get(key):
            await asyncio.sleep(delay)
            return f"value_for_{key}"

        async def delayed_set(key, value, ttl=None):
            await asyncio.sleep(delay)
            return True

        client.get = delayed_get
        client.set = delayed_set
        client.delete = AsyncMock(return_value=True)
        client.health_check = AsyncMock(
            return_value={"status": "healthy", "latency_ms": delay * 1000}
        )

        return client












