#!/usr/bin/env python3
"""
Custom Exception Hierarchy for SSE Streaming Microservice

This module defines a structured exception hierarchy for the entire application.
All exceptions inherit from SSEBaseException for consistent error handling.

Architectural Decision: Structured exception hierarchy
- Easy to catch specific error types
- Thread ID correlation for debugging
- Consistent error messages and logging

Author: System Architect
Date: 2025-12-05
"""

from typing import Any


class SSEBaseException(Exception):
    """
    Base exception for all SSE streaming errors.

    All custom exceptions inherit from this class to enable:
    - Consistent error handling
    - Thread ID correlation
    - Structured error logging

    Attributes:
        message: Error message
        thread_id: Thread ID for correlation (if available)
        details: Additional error details
    """

    def __init__(
        self,
        message: str,
        thread_id: str | None = None,
        details: dict[str, Any] | None = None
    ):
        self.message = message
        self.thread_id = thread_id
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging/API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "thread_id": self.thread_id,
            "details": self.details
        }


# ============================================================================
# Configuration Exceptions
# ============================================================================

class ConfigurationError(SSEBaseException):
    """Raised when configuration is invalid or missing."""
    pass


# ============================================================================
# Cache Exceptions
# ============================================================================

class CacheException(SSEBaseException):
    """Base exception for cache-related errors."""
    pass


class CacheConnectionError(CacheException):
    """Raised when unable to connect to cache (Redis)."""
    pass


class CacheKeyError(CacheException):
    """Raised when cache key operation fails."""
    pass


# ============================================================================
# Queue Exceptions
# ============================================================================

class QueueException(SSEBaseException):
    """Base exception for message queue errors."""
    pass


class QueueFullError(QueueException):
    """Raised when queue is full (backpressure)."""
    pass


class QueueConsumerError(QueueException):
    """Raised when queue consumer encounters an error."""
    pass


# ============================================================================
# Provider Exceptions
# ============================================================================

class ProviderException(SSEBaseException):
    """Base exception for LLM provider errors."""
    pass


class ProviderNotAvailableError(ProviderException):
    """Raised when LLM provider is not available."""
    pass


class ProviderAuthenticationError(ProviderException):
    """Raised when LLM provider authentication fails."""
    pass


class ProviderTimeoutError(ProviderException):
    """Raised when LLM provider request times out."""
    pass


class ProviderAPIError(ProviderException):
    """Raised when LLM provider API returns an error."""
    pass


class AllProvidersDownError(ProviderException):
    """Raised when all LLM providers are unavailable."""
    pass


# ============================================================================
# Circuit Breaker Exceptions
# ============================================================================

class CircuitBreakerError(SSEBaseException):
    """Base exception for circuit breaker errors."""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """
    Raised when circuit breaker is open (fail fast).

    STAGE-CB.3: Circuit breaker open exception

    This exception indicates that the circuit breaker is open and
    requests are being rejected to prevent cascade failures.
    """
    pass


# ============================================================================
# Rate Limiting Exceptions
# ============================================================================

class RateLimitError(SSEBaseException):
    """Base exception for rate limiting errors."""
    pass


class RateLimitExceededError(RateLimitError):
    """
    Raised when rate limit is exceeded.

    STAGE-3: Rate limit exceeded exception

    This exception is raised when a user/IP exceeds their rate limit.
    """
    pass


# ============================================================================
# Streaming Exceptions
# ============================================================================

class StreamingException(SSEBaseException):
    """Base exception for streaming errors."""
    pass


class StreamingTimeoutError(StreamingException):
    """Raised when streaming operation times out."""
    pass


class ConnectionPoolExhaustedError(StreamingException):
    """Raised when connection pool is exhausted."""
    pass


# ============================================================================
# Validation Exceptions
# ============================================================================

class ValidationError(SSEBaseException):
    """Raised when request validation fails."""
    pass


class InvalidModelError(ValidationError):
    """Raised when invalid model is specified."""
    pass


class InvalidInputError(ValidationError):
    """Raised when input validation fails."""
    pass


# ============================================================================
# Execution Tracker Exceptions
# ============================================================================

class ExecutionTrackerError(SSEBaseException):
    """Base exception for execution tracker errors."""
    pass


class StageNotFoundError(ExecutionTrackerError):
    """Raised when stage is not found in execution tracker."""
    pass
