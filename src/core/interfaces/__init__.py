"""
Core Interfaces Module

This module provides abstract interfaces and protocols for core components,
enabling dependency injection, testability, and loose coupling.

Components:
-----------
- **cache.py**: CacheBackend protocol for cache implementations
- **message_queue.py**: MessageQueue interface for queue implementations

Architecture:
------------
Interfaces follow the Protocol pattern (PEP 544) for structural subtyping:
- Runtime type checking with @runtime_checkable
- Duck typing with type safety
- No inheritance required
- Easy mocking for tests

Usage:
------
```python
from src.core.interfaces import CacheBackend, MessageQueue

# Dependency injection
def process_request(cache: CacheBackend, queue: MessageQueue):
    # Works with any implementation
    await cache.get("key")
    await queue.produce(message)
```

Benefits:
---------
1. **Testability**: Easy to mock implementations
2. **Flexibility**: Swap implementations without code changes
3. **Type Safety**: Static type checking with mypy/pyright
4. **Loose Coupling**: Components depend on interfaces, not concrete classes

Author: System Architect
Date: 2025-12-08
"""

from src.core.interfaces.cache import CacheBackend, InMemoryCache
from src.core.interfaces.message_queue import MessageQueue, QueueMessage

__all__ = [
    # Cache interfaces
    "CacheBackend",
    "InMemoryCache",
    # Message queue interfaces
    "MessageQueue",
    "QueueMessage",
]
