"""
Circuit Breaker Exceptions

All exceptions related to circuit breaker operations

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class CircuitBreakerError(SSEBaseError):
    """Base exception for circuit breaker errors."""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """
    Raised when circuit breaker is open (fail fast).

    This exception indicates that the circuit breaker is open and
    requests are being rejected to prevent cascade failures.

    The circuit will transition to half-open state after the recovery timeout,
    at which point test requests will be allowed through.

    Common causes:
    - Too many consecutive failures
    - Provider is down
    - Network issues
    - Timeout threshold exceeded
    """
    pass
