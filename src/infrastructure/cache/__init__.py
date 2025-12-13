"""
Cache Module

Provides multi-tier caching (L1 in-memory + L2 Redis).
"""

from .cache_manager import (
    CacheManager,
    close_cache,
    get_cache_manager,
    init_cache,
)

__all__ = [
    "CacheManager",
    "get_cache_manager",
    "init_cache",
    "close_cache",
]
