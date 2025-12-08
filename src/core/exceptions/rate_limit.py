"""
Rate Limiting Exceptions

All exceptions related to rate limiting operations

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class RateLimitError(SSEBaseError):
    """Base exception for rate limiting errors."""
    pass


class RateLimitExceededError(RateLimitError):
    """
    Raised when rate limit is exceeded.

    This exception is raised when a user/IP exceeds their rate limit.
    Clients should implement exponential backoff and retry after the reset time.

    The response should include:
    - X-RateLimit-Limit: Maximum requests allowed
    - X-RateLimit-Remaining: Requests remaining
    - X-RateLimit-Reset: Time when limit resets (Unix timestamp)

    Common causes:
    - Too many requests in time window
    - Burst limit exceeded
    - Distributed attack
    """
    pass
