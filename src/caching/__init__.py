"""
Cache Module

Provides multi-tier caching (L1 in-memory + L2 Redis).
"""

from .cache_manager import (
    CacheManager,
    LRUCache,
    close_cache,
    get_cache_manager,
    init_cache,
)

__all__ = [
    "CacheManager",
    "LRUCache",
    "get_cache_manager",
    "init_cache",
    "close_cache",
]
