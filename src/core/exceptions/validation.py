"""
Validation Exceptions

All exceptions related to request validation

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class ValidationError(SSEBaseError):
    """
    Raised when request validation fails.

    This is the base class for all validation-related errors.
    """
    pass


class InvalidModelError(ValidationError):
    """
    Raised when invalid model is specified.

    This error should include:
    - The requested model name
    - The provider name
    - List of supported models
    - Suggestion for a valid model

    Example:
        raise InvalidModelError(
            f"Model '{model}' not supported by provider '{provider}'",
            details={
                "requested_model": model,
                "provider": provider,
                "supported_models": ["gpt-3.5-turbo", "gpt-4"],
                "suggestion": "Try: gpt-3.5-turbo"
            }
        )
    """
    pass


class InvalidInputError(ValidationError):
    """
    Raised when input validation fails.

    Common causes:
    - Empty query
    - Query too long
    - Invalid characters
    - Missing required fields
    - Invalid field types
    """
    pass
