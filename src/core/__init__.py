"""
Core Module

Foundational components: logging, exceptions, and execution tracking.
"""

from .exceptions import (
    CacheConnectionError,
    CacheError,
    CacheKeyError,
    CircuitBreakerOpenError,
    ConfigurationError,
    ProviderError,
    ProviderNotAvailableError,
    ProviderTimeoutError,
    QueueError,
    QueueFullError,
    RateLimitExceededError,
    SSEBaseError,
    StreamingError,
    ValidationError,
)
from .logging import (
    clear_thread_id,
    get_logger,
    get_thread_id,
    log_stage,
    set_thread_id,
    setup_logging,
)
from .observability.execution_tracker import (
    ExecutionTracker,
    StageExecution,
    get_tracker,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "set_thread_id",
    "get_thread_id",
    "clear_thread_id",
    "log_stage",
    "SSEBaseError",
    "ConfigurationError",
    "CacheError",
    "CacheConnectionError",
    "CacheKeyError",
    "QueueError",
    "QueueFullError",
    "ProviderError",
    "ProviderNotAvailableError",
    "ProviderTimeoutError",
    "CircuitBreakerOpenError",
    "RateLimitExceededError",
    "StreamingError",
    "ValidationError",
    "ExecutionTracker",
    "StageExecution",
    "get_tracker",
]
