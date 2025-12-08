"""
Cache-Related Exceptions

All exceptions related to caching operations (Redis, in-memory cache, etc.)

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class CacheError(SSEBaseError):
    """Base exception for cache-related errors."""
    pass


class CacheConnectionError(CacheError):
    """
    Raised when unable to connect to cache (Redis).

    Common causes:
    - Redis server is down
    - Network connectivity issues
    - Incorrect host/port configuration
    - Authentication failure
    """
    pass


class CacheKeyError(CacheError):
    """
    Raised when cache key operation fails.

    Common causes:
    - Invalid key format
    - Key too long
    - Operation timeout
    - Memory limit exceeded
    """
    pass
