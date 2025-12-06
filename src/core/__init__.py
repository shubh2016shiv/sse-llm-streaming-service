"""
Core Module

Foundational components: logging, exceptions, and execution tracking.
"""

from .exceptions import (
    CacheConnectionError,
    CacheException,
    CacheKeyError,
    CircuitBreakerOpenError,
    ConfigurationError,
    ProviderException,
    ProviderNotAvailableError,
    ProviderTimeoutError,
    QueueException,
    QueueFullError,
    RateLimitExceededError,
    SSEBaseException,
    StreamingException,
    ValidationError,
)
from .execution_tracker import (
    ExecutionTracker,
    StageExecution,
    get_tracker,
)
from .logging import (
    clear_thread_id,
    get_logger,
    get_thread_id,
    log_stage,
    set_thread_id,
    setup_logging,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "set_thread_id",
    "get_thread_id",
    "clear_thread_id",
    "log_stage",
    "SSEBaseException",
    "ConfigurationError",
    "CacheException",
    "CacheConnectionError",
    "CacheKeyError",
    "QueueException",
    "QueueFullError",
    "ProviderException",
    "ProviderNotAvailableError",
    "ProviderTimeoutError",
    "CircuitBreakerOpenError",
    "RateLimitExceededError",
    "StreamingException",
    "ValidationError",
    "ExecutionTracker",
    "StageExecution",
    "get_tracker",
]
