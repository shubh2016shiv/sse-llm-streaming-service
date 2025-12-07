"""
Validation Exceptions Module

Custom exception hierarchy for validation errors with detailed context.

ENTERPRISE DECISION: Custom Exception Hierarchy
------------------------------------------------
Instead of using generic ValueError, we define specific exception types.
This allows:
- Precise error handling (catch specific validation failures)
- Better error messages with context
- Easier debugging (exception type tells you what failed)
- Client-friendly error responses (map exception to HTTP status)
"""

from typing import Any


class ValidationError(Exception):
    """
    Base validation error.

    DESIGN PATTERN: Exception Hierarchy
    ------------------------------------
    All validation errors inherit from this base class, allowing:
    - Catch all validation errors: except ValidationError
    - Catch specific errors: except QueryValidationError
    - Add common behavior (logging, metrics) in base class
    """

    def __init__(self, message: str, field: str | None = None, value: Any = None):
        """
        Initialize validation error with context.

        Args:
            message: Human-readable error message
            field: Field name that failed validation (optional)
            value: Value that failed validation (optional, sanitized)
        """
        self.message = message
        self.field = field
        self.value = value
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for API responses.

        ENTERPRISE PATTERN: Structured Error Responses
        -----------------------------------------------
        Returns consistent error format for API clients:
        {
            "error": "validation_error",
            "message": "Query too long",
            "field": "query",
            "details": {...}
        }
        """
        result = {
            "error": self.__class__.__name__,
            "message": self.message,
        }

        if self.field:
            result["field"] = self.field

        if self.value is not None:
            # Sanitize value for security (don't leak sensitive data)
            result["value_type"] = type(self.value).__name__

        return result


class QueryValidationError(ValidationError):
    """Query content validation failed."""
    pass


class ModelValidationError(ValidationError):
    """Model identifier validation failed."""
    pass


class ProviderValidationError(ValidationError):
    """Provider identifier validation failed."""
    pass


class RateLimitValidationError(ValidationError):
    """Rate limit validation failed."""
    pass


class SecurityValidationError(ValidationError):
    """Security validation failed (malicious content detected)."""
    pass


class ConfigValidationError(ValidationError):
    """Configuration validation failed."""
    pass
