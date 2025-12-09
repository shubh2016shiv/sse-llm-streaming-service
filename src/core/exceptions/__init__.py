"""
Exception Module

Structured exception hierarchy for the SSE streaming microservice.
All exceptions are organized by theme for better maintainability and debuggability.

Module Structure:
-----------------
- **base.py**: SSEBaseError base class + ConfigurationError
- **cache.py**: Cache-related exceptions (Redis, etc.)
- **queue.py**: Message queue exceptions
- **provider.py**: LLM provider exceptions
- **circuit_breaker.py**: Circuit breaker exceptions
- **rate_limit.py**: Rate limiting exceptions
- **streaming.py**: SSE streaming exceptions
- **validation.py**: Request validation exceptions
- **tracker.py**: Execution tracker exceptions

Benefits of Separation:
----------------------
1. **Easy to Find**: Exceptions grouped by concern
2. **Easy to Extend**: Add new exceptions to appropriate file
3. **Easy to Debug**: Clear file names indicate exception purpose
4. **Better Imports**: Import only what you need
5. **Maintainability**: Small, focused files

Usage:
------
```python
# Import specific exceptions
from src.core.exceptions import CacheConnectionError, ProviderTimeoutError

# Or import by category
from src.core.exceptions.cache import CacheError, CacheConnectionError
from src.core.exceptions.provider import ProviderError, AllProvidersDownError
```

Author: System Architect
Date: 2025-12-08
"""

# Base exception
from src.core.exceptions.base import ConfigurationError, SSEBaseError

# Cache exceptions
from src.core.exceptions.cache import CacheConnectionError, CacheError, CacheKeyError

# Circuit breaker exceptions
from src.core.exceptions.circuit_breaker import (
    CircuitBreakerError,
    CircuitBreakerOpenError,
)

# Connection Pool exceptions
from src.core.exceptions.connection_pool import (
    ConnectionPoolError,
    ConnectionPoolExhaustedError,
    UserConnectionLimitError,
)

# Provider exceptions
from src.core.exceptions.provider import (
    AllProvidersDownError,
    ProviderAPIError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderNotAvailableError,
    ProviderTimeoutError,
)

# Queue exceptions
from src.core.exceptions.queue import QueueConsumerError, QueueError, QueueFullError

# Rate limit exceptions
from src.core.exceptions.rate_limit import RateLimitError, RateLimitExceededError

# Streaming exceptions
from src.core.exceptions.streaming import (
    StreamingError,
    StreamingTimeoutError,
)

# Execution tracker exceptions
from src.core.exceptions.tracker import ExecutionTrackerError, StageNotFoundError

# Validation exceptions
from src.core.exceptions.validation import (
    InvalidInputError,
    InvalidModelError,
    ValidationError,
)

__all__ = [
    # Base
    "SSEBaseError",
    "ConfigurationError",
    # Cache
    "CacheError",
    "CacheConnectionError",
    "CacheKeyError",
    # Queue
    "QueueError",
    "QueueFullError",
    "QueueConsumerError",
    # Provider
    "ProviderError",
    "ProviderNotAvailableError",
    "ProviderAuthenticationError",
    "ProviderTimeoutError",
    "ProviderAPIError",
    "AllProvidersDownError",
    # Circuit Breaker
    "CircuitBreakerError",
    "CircuitBreakerOpenError",
    # Rate Limit
    "RateLimitError",
    "RateLimitExceededError",
    # Connection Pool
    "ConnectionPoolError",
    "ConnectionPoolExhaustedError",
    "UserConnectionLimitError",
    # Streaming
    "StreamingError",
    "StreamingTimeoutError",
    # Validation
    "ValidationError",
    "InvalidModelError",
    "InvalidInputError",
    # Execution Tracker
    "ExecutionTrackerError",
    "StageNotFoundError",
]
