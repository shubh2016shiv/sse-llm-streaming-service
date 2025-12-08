"""
Base Exception Class

This module contains ONLY the base exception class that all other exceptions inherit from.
All specialized exceptions are in their respective themed modules.

Author: System Architect
Date: 2025-12-08
"""

from typing import Any


class SSEBaseError(Exception):
    """
    Base exception for all SSE streaming errors.

    All custom exceptions inherit from this class to enable:
    - Consistent error handling
    - Thread ID correlation
    - Structured error logging
    - Rich context for debugging

    Attributes:
        message: Error message
        thread_id: Thread ID for correlation (if available)
        details: Additional error details (dict)

    Example:
        raise ProviderError(
            "Failed to connect to OpenAI",
            thread_id="abc-123",
            details={
                "provider": "openai",
                "error_code": "connection_timeout",
                "retry_count": 3
            }
        )
    """

    def __init__(
        self, message: str, thread_id: str | None = None, details: dict[str, Any] | None = None
    ):
        self.message = message
        self.thread_id = thread_id
        self.details = (details or {}).copy()  # Create a copy to prevent external modification
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert exception to dictionary for logging/API responses.

        Returns:
            Dict with error_type, message, thread_id, and details
        """
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "thread_id": self.thread_id,
            "details": self.details,
        }

    def with_suggestion(self, suggestion: str) -> "SSEBaseError":
        """
        Add a suggestion to help users fix the error.

        Args:
            suggestion: Helpful suggestion for resolving the error

        Returns:
            Self (for method chaining)
        """
        self.details["suggestion"] = suggestion
        return self

    def with_context(self, **context) -> "SSEBaseError":
        """
        Add additional context to the error details.

        Args:
            **context: Key-value pairs to add to details

        Returns:
            Self (for method chaining)
        """
        self.details.update(context)
        return self

    def __repr__(self) -> str:
        """
        Return detailed string representation for debugging.

        Returns:
            String representation with class name, message, thread_id, and details

        Example:
            >>> error = ProviderTimeoutError(
            ...     "Timeout", thread_id="abc-123", details={"timeout": 30}
            ... )
            >>> repr(error)
            "ProviderTimeoutError(message='Timeout', thread_id='abc-123', details={'timeout': 30})"
        """
        details_str = f", details={self.details}" if self.details else ""
        thread_id_str = f", thread_id='{self.thread_id}'" if self.thread_id else ""
        return f"{self.__class__.__name__}(message='{self.message}'{thread_id_str}{details_str})"

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        message: str | None = None,
        thread_id: str | None = None,
        **details
    ) -> "SSEBaseError":
        """
        Create SSEBaseError from another exception.

        Useful for wrapping third-party exceptions with additional context.

        Args:
            exc: Original exception to wrap
            message: Custom message (defaults to original exception message)
            thread_id: Thread ID for correlation
            **details: Additional context to include

        Returns:
            New SSEBaseError instance with wrapped exception details

        Example:
            >>> try:
            ...     await redis.connect()
            ... except redis.ConnectionError as e:
            ...     raise CacheConnectionError.from_exception(
            ...         e,
            ...         thread_id="abc-123",
            ...         host="localhost",
            ...         port=6379
            ...     )
        """
        error_message = message or str(exc)
        error_details = {
            "original_error": exc.__class__.__name__,
            "original_message": str(exc),
            **details
        }
        return cls(error_message, thread_id=thread_id, details=error_details)


# Configuration exception (kept here as it's fundamental)
class ConfigurationError(SSEBaseError):
    """Raised when configuration is invalid or missing."""
    pass
