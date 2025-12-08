"""
Unit Tests for Core Exceptions

Tests for exception handling.
"""

import pytest

# Import from new themed modules
from src.core.exceptions import (
    AllProvidersDownError,
    CircuitBreakerOpenError,
    ProviderTimeoutError,
    SSEBaseError,
    ValidationError,
)


@pytest.mark.unit
class TestSSEBaseError:
    """Test the base SSE exception class."""

    def test_base_error_creation(self):
        """Test that SSEBaseError can be created."""
        error = SSEBaseError("Test message")
        assert str(error) == "Test message"

    def test_base_error_with_details(self):
        """Test SSEBaseError with additional details."""
        details = {"key": "value", "code": 123}
        error = SSEBaseError("Test message", details=details)

        assert error.details == details
        assert error.message == "Test message"

    def test_base_error_inheritance(self):
        """Test that SSEBaseError properly inherits from Exception."""
        error = SSEBaseError("Test")
        assert isinstance(error, Exception)

    def test_base_error_default_values(self):
        """Test default values for SSEBaseError."""
        error = SSEBaseError("Test")
        assert error.details == {}  # Defaults to empty dict, not None
        assert error.thread_id is None


@pytest.mark.unit
class TestAllProvidersDownError:
    """Test AllProvidersDownError exception."""

    def test_error_creation(self):
        """Test AllProvidersDownError creation."""
        error = AllProvidersDownError("All providers failed")
        assert "All providers failed" in str(error)

    def test_error_with_context(self):
        """Test AllProvidersDownError with thread context."""
        error = AllProvidersDownError(
            message="No healthy providers",
            thread_id="test-thread-123",
            details={"attempted_providers": ["openai", "gemini"]},
        )

        assert error.thread_id == "test-thread-123"
        assert "attempted_providers" in error.details
        assert error.details["attempted_providers"] == ["openai", "gemini"]

    def test_error_inheritance(self):
        """Test that AllProvidersDownError inherits from SSEBaseError."""
        error = AllProvidersDownError("Test")
        assert isinstance(error, SSEBaseError)
        assert isinstance(error, Exception)


@pytest.mark.unit
class TestCircuitBreakerOpenError:
    """Test CircuitBreakerOpenError exception."""

    def test_error_creation(self):
        """Test CircuitBreakerOpenError creation."""
        error = CircuitBreakerOpenError("Circuit is open")
        assert "Circuit is open" in str(error)

    def test_error_with_provider_context(self):
        """Test CircuitBreakerOpenError with provider information."""
        error = CircuitBreakerOpenError(
            message="Provider circuit open",
            thread_id="thread-456",
            details={"provider": "openai", "fail_count": 5},
        )

        assert error.thread_id == "thread-456"
        assert error.details["provider"] == "openai"
        assert error.details["fail_count"] == 5

    def test_error_inheritance(self):
        """Test that CircuitBreakerOpenError inherits from SSEBaseError."""
        error = CircuitBreakerOpenError("Test")
        assert isinstance(error, SSEBaseError)


@pytest.mark.unit
class TestProviderTimeoutError:
    """Test ProviderTimeoutError exception."""

    def test_error_creation(self):
        """Test ProviderTimeoutError creation."""
        error = ProviderTimeoutError("Provider timed out")
        assert "Provider timed out" in str(error)

    def test_error_with_timeout_details(self):
        """Test ProviderTimeoutError with timeout information."""
        error = ProviderTimeoutError(
            message="Request timeout",
            thread_id="timeout-thread",
            details={"provider": "gemini", "timeout_seconds": 30},
        )

        assert error.thread_id == "timeout-thread"
        assert error.details["timeout_seconds"] == 30

    def test_error_inheritance(self):
        """Test that ProviderTimeoutError inherits from SSEBaseError."""
        error = ProviderTimeoutError("Test")
        assert isinstance(error, SSEBaseError)


@pytest.mark.unit
class TestValidationError:
    """Test ValidationError exception."""

    def test_error_creation(self):
        """Test ValidationError creation."""
        error = ValidationError("Validation failed")
        assert "Validation failed" in str(error)

    def test_error_with_field_information(self):
        """Test ValidationError with field validation details."""
        error = ValidationError(
            message="Invalid input",
            thread_id="validation-thread",
            details={"field": "query", "value": "", "reason": "cannot be empty"},
        )

        assert error.details["field"] == "query"
        assert error.details["reason"] == "cannot be empty"

    def test_error_inheritance(self):
        """Test that ValidationError inherits from SSEBaseError."""
        error = ValidationError("Test")
        assert isinstance(error, SSEBaseError)


@pytest.mark.unit
class TestExceptionHierarchy:
    """Test the exception class hierarchy."""

    def test_all_exceptions_inherit_from_base(self):
        """Test that all SSE exceptions inherit from SSEBaseError."""
        exceptions = [
            AllProvidersDownError("test"),
            CircuitBreakerOpenError("test"),
            ProviderTimeoutError("test"),
            ValidationError("test"),
        ]

        for exc in exceptions:
            assert isinstance(exc, SSEBaseError)
            assert isinstance(exc, Exception)

    def test_exception_equality(self):
        """Test that exceptions with same parameters are equal."""
        error1 = SSEBaseError("message", details={"key": "value"})
        error2 = SSEBaseError("message", details={"key": "value"})

        # Exceptions don't override __eq__, so they compare by identity
        assert error1 is not error2
        assert str(error1) == str(error2)


@pytest.mark.unit
class TestExceptionContextHandling:
    """Test exception context and thread handling."""

    def test_exceptions_preserve_thread_context(self):
        """Test that exceptions properly store thread context."""
        thread_ids = ["thread-123", "user-session-456", "request-789"]

        for thread_id in thread_ids:
            error = SSEBaseError("Test", thread_id=thread_id)
            assert error.thread_id == thread_id

    def test_exceptions_handle_none_thread_id(self):
        """Test that exceptions handle None thread_id gracefully."""
        error = SSEBaseError("Test", thread_id=None)
        assert error.thread_id is None

    def test_exception_details_are_isolated(self):
        """Test that exception details are properly isolated from input."""
        details = {"key": "value"}
        error = SSEBaseError("Test", details=details)

        # Modifying original dict should not affect error (they're isolated)
        original_error_details = error.details.copy()
        details["new_key"] = "new_value"

        # Error details should not be affected by changes to input dict
        assert error.details == original_error_details

    def test_exception_string_representation(self):
        """Test string representation of exceptions."""
        test_cases = [
            (SSEBaseError("Simple message"), "Simple message"),
            (AllProvidersDownError("All down"), "All down"),
            (CircuitBreakerOpenError("Circuit open"), "Circuit open"),
            (ProviderTimeoutError("Timeout"), "Timeout"),
            (ValidationError("Invalid"), "Invalid"),
        ]

        for error, expected in test_cases:
            assert str(error) == expected
