"""
Cache Backend Protocol

This module defines the abstract protocol for cache backend implementations,
enabling dependency injection and testability.

Architectural Decision: Protocol-based abstraction
- Enables multiple cache backend implementations (Redis, Memcached, In-Memory)
- Facilitates testing with mock implementations
- Follows dependency inversion principle
- Type-safe interface with runtime checking

Author: System Architect
Date: 2025-12-08
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """
    Protocol defining the interface for cache backend implementations.

    This protocol ensures all cache backends provide a consistent interface
    for get, set, delete, and other cache operations.

    Implementations:
    - RedisClient: Production Redis-backed cache
    - InMemoryCache: Testing/development in-memory cache
    - MemcachedClient: Alternative distributed cache

    Usage:
        def process_with_cache(cache: CacheBackend, key: str) -> str | None:
            # Works with any CacheBackend implementation
            return await cache.get(key)

    Benefits:
    - Dependency injection for testability
    - Easy to swap implementations
    - Type-safe with mypy/pyright
    - Runtime validation with @runtime_checkable
    """

    async def connect(self) -> None:
        """
        Establish connection to the cache backend.

        Raises:
            CacheConnectionError: If connection fails
        """
        ...

    async def disconnect(self) -> None:
        """
        Close connection to the cache backend.
        """
        ...

    async def ping(self) -> bool:
        """
        Check if cache backend is healthy.

        Returns:
            bool: True if healthy, False otherwise
        """
        ...

    async def get(self, key: str) -> str | None:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Optional[str]: Value or None if not found

        Raises:
            CacheKeyError: If operation fails
        """
        ...

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to store
            ttl: Time-to-live in seconds (optional)
            nx: Only set if key doesn't exist
            xx: Only set if key exists

        Returns:
            bool: True if set successfully

        Raises:
            CacheKeyError: If operation fails
        """
        ...

    async def delete(self, *keys: str) -> int:
        """
        Delete keys from cache.

        Args:
            *keys: Keys to delete

        Returns:
            int: Number of keys deleted

        Raises:
            CacheKeyError: If operation fails
        """
        ...

    async def exists(self, *keys: str) -> int:
        """
        Check if keys exist in cache.

        Args:
            *keys: Keys to check

        Returns:
            int: Number of keys that exist
        """
        ...

    async def expire(self, key: str, ttl: int) -> bool:
        """
        Set TTL on a key.

        Args:
            key: Cache key
            ttl: Time-to-live in seconds

        Returns:
            bool: True if TTL was set
        """
        ...

    async def ttl(self, key: str) -> int:
        """
        Get TTL of a key.

        Args:
            key: Cache key

        Returns:
            int: TTL in seconds, -1 if no TTL, -2 if key doesn't exist
        """
        ...

    # Hash operations
    async def hget(self, name: str, key: str) -> str | None:
        """Get hash field value."""
        ...

    async def hset(self, name: str, key: str, value: str) -> int:
        """Set hash field value."""
        ...

    async def hgetall(self, name: str) -> dict[str, str]:
        """Get all hash fields."""
        ...

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
        ...

    # Counter operations
    async def incr(self, key: str) -> int:
        """Increment counter."""
        ...

    async def incrby(self, key: str, amount: int) -> int:
        """Increment counter by amount."""
        ...

    async def decr(self, key: str) -> int:
        """Decrement counter."""
        ...

    # Health check
    async def health_check(self) -> dict[str, Any]:
        """
        Perform comprehensive health check.

        Returns:
            Dict with health status and metrics
        """
        ...


class InMemoryCache:
    """
    Simple in-memory cache implementation for testing.

    Implements the CacheBackend protocol without external dependencies.
    Useful for unit tests and development environments.

    Note: This is NOT thread-safe and NOT distributed.
    Use only for testing purposes.
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}
        self._connected = False

    async def connect(self) -> None:
        """Simulate connection."""
        self._connected = True

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False
        self._store.clear()
        self._ttls.clear()

    async def ping(self) -> bool:
        """Check if connected."""
        return self._connected

    async def get(self, key: str) -> str | None:
        """Get value from in-memory store."""
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """Set value in in-memory store."""
        if nx and key in self._store:
            return False
        if xx and key not in self._store:
            return False

        self._store[key] = value
        if ttl:
            self._ttls[key] = ttl
        return True

    async def delete(self, *keys: str) -> int:
        """Delete keys from in-memory store."""
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._ttls.pop(key, None)
                count += 1
        return count

    async def exists(self, *keys: str) -> int:
        """Check if keys exist."""
        return sum(1 for key in keys if key in self._store)

    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL on key."""
        if key in self._store:
            self._ttls[key] = ttl
            return True
        return False

    async def ttl(self, key: str) -> int:
        """Get TTL of key."""
        if key not in self._store:
            return -2
        return self._ttls.get(key, -1)

    # Hash operations (simplified)
    async def hget(self, name: str, key: str) -> str | None:
        """Get hash field (stored as JSON string)."""
        import json
        data = self._store.get(name)
        if data:
            return json.loads(data).get(key)
        return None

    async def hset(self, name: str, key: str, value: str) -> int:
        """Set hash field."""
        import json
        data = json.loads(self._store.get(name, "{}"))
        data[key] = value
        self._store[name] = json.dumps(data)
        return 1

    async def hgetall(self, name: str) -> dict[str, str]:
        """Get all hash fields."""
        import json
        data = self._store.get(name)
        return json.loads(data) if data else {}

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
        import json
        data = json.loads(self._store.get(name, "{}"))
        count = sum(1 for key in keys if data.pop(key, None) is not None)
        self._store[name] = json.dumps(data)
        return count

    # Counter operations
    async def incr(self, key: str) -> int:
        """Increment counter."""
        value = int(self._store.get(key, "0")) + 1
        self._store[key] = str(value)
        return value

    async def incrby(self, key: str, amount: int) -> int:
        """Increment counter by amount."""
        value = int(self._store.get(key, "0")) + amount
        self._store[key] = str(value)
        return value

    async def decr(self, key: str) -> int:
        """Decrement counter."""
        value = int(self._store.get(key, "0")) - 1
        self._store[key] = str(value)
        return value

    async def health_check(self) -> dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy" if self._connected else "unhealthy",
            "connected": self._connected,
            "keys_count": len(self._store)
        }
