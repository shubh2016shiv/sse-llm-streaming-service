"""
LLM Provider Exceptions

All exceptions related to LLM provider operations (OpenAI, DeepSeek, Gemini, etc.)

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class ProviderError(SSEBaseError):
    """Base exception for LLM provider errors."""
    pass


class ProviderNotAvailableError(ProviderError):
    """
    Raised when LLM provider is not available.

    Common causes:
    - Provider API is down
    - Network connectivity issues
    - Rate limiting by provider
    - Circuit breaker is open
    """
    pass


class ProviderAuthenticationError(ProviderError):
    """
    Raised when LLM provider authentication fails.

    Common causes:
    - Invalid API key
    - Expired API key
    - Insufficient permissions
    - Account suspended
    """
    pass


class ProviderTimeoutError(ProviderError):
    """
    Raised when LLM provider request times out.

    Common causes:
    - Slow provider response
    - Network latency
    - Large request payload
    - Provider overload
    """
    pass


class ProviderAPIError(ProviderError):
    """
    Raised when LLM provider API returns an error.

    Common causes:
    - Invalid request format
    - Unsupported model
    - Content policy violation
    - Token limit exceeded
    """
    pass


class AllProvidersDownError(ProviderError):
    """
    Raised when all LLM providers are unavailable.

    This is a critical error indicating complete service outage.
    All fallback providers have been exhausted.
    """
    pass
