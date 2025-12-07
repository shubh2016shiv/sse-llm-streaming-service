"""
Additional Edge Case Tests for Logging Module

Tests edge cases and error conditions for structured logging.
"""

from unittest.mock import patch

import pytest

from src.core.logging.logger import (
    add_thread_id,
    add_timestamp,
    clear_thread_id,
    get_logger,
    log_stage,
    redact_pii,
    set_thread_id,
)


@pytest.mark.unit
class TestLoggingEdgeCases:
    """Test edge cases for logging functionality."""

    def test_get_logger_with_empty_name(self):
        """Test get_logger with empty string name."""
        logger = get_logger("")
        assert logger is not None
        assert hasattr(logger, "info")

    def test_get_logger_with_very_long_name(self):
        """Test get_logger with very long module name."""
        long_name = "a" * 1000
        logger = get_logger(long_name)
        assert logger is not None

    def test_get_logger_with_special_characters(self):
        """Test get_logger with special characters in name."""
        special_names = [
            "module.with.dots",
            "module-with-dashes",
            "module_with_underscores",
            "module/with/slashes",
            "module:with:colons",
        ]

        for name in special_names:
            logger = get_logger(name)
            assert logger is not None
            assert hasattr(logger, "info")

    def test_set_thread_id_with_none(self):
        """Test set_thread_id with None value."""
        # Should not raise exception
        set_thread_id(None)
        clear_thread_id()

    def test_set_thread_id_with_empty_string(self):
        """Test set_thread_id with empty string."""
        set_thread_id("")
        # Should not raise exception
        clear_thread_id()

    def test_set_thread_id_with_very_long_id(self):
        """Test set_thread_id with very long thread ID."""
        long_id = "thread-" + "x" * 10000
        set_thread_id(long_id)
        clear_thread_id()

    def test_multiple_set_thread_id_calls(self):
        """Test multiple consecutive set_thread_id calls."""
        set_thread_id("thread-1")
        set_thread_id("thread-2")
        set_thread_id("thread-3")
        # Last one should win
        clear_thread_id()

    def test_clear_thread_id_without_setting(self):
        """Test clear_thread_id when no thread ID was set."""
        # Should not raise exception
        clear_thread_id()
        clear_thread_id()  # Multiple clears

    def test_log_stage_with_none_stage_id(self):
        """Test log_stage with None stage ID."""
        logger = get_logger("test")

        with patch.object(logger, "info") as mock_info:
            log_stage(logger, None, "Test message")
            mock_info.assert_called_once()

    def test_log_stage_with_empty_message(self):
        """Test log_stage with empty message."""
        logger = get_logger("test")

        with patch.object(logger, "info") as mock_info:
            log_stage(logger, "1", "")
            mock_info.assert_called_once()

    def test_log_stage_with_very_long_message(self):
        """Test log_stage with very long message."""
        logger = get_logger("test")
        long_message = "x" * 100000

        with patch.object(logger, "info") as mock_info:
            log_stage(logger, "1", long_message)
            mock_info.assert_called_once()

    def test_log_stage_with_invalid_level(self):
        """Test log_stage with invalid log level."""
        logger = get_logger("test")

        # Should raise AttributeError when trying to get invalid level
        with pytest.raises(AttributeError):
            log_stage(logger, "1", "Test", level="invalid_level")

    def test_log_stage_with_numeric_stage(self):
        """Test log_stage with numeric stage ID."""
        logger = get_logger("test")

        with patch.object(logger, "info") as mock_info:
            log_stage(logger, 123, "Numeric stage")
            mock_info.assert_called_once()

    def test_log_stage_with_complex_kwargs(self):
        """Test log_stage with complex nested kwargs."""
        logger = get_logger("test")

        complex_data = {"nested": {"key": "value"}, "list": [1, 2, 3], "tuple": (4, 5, 6)}

        with patch.object(logger, "info") as mock_info:
            log_stage(logger, "1", "Complex data", **complex_data)
            mock_info.assert_called_once()

    def test_log_stage_with_exception_in_kwargs(self):
        """Test log_stage with exception object in kwargs."""
        logger = get_logger("test")

        try:
            raise ValueError("Test error")
        except ValueError as e:
            with patch.object(logger, "info") as mock_info:
                log_stage(logger, "1", "Error occurred", error=e)
                mock_info.assert_called_once()


@pytest.mark.unit
class TestPIIRedactionEdgeCases:
    """Test edge cases for PII redaction."""

    def test_redact_pii_with_multiple_emails(self):
        """Test PII redaction with multiple email addresses."""
        from structlog.types import EventDict

        event_dict: EventDict = {
            "event": "User test@example.com contacted admin@example.com about user2@test.org"
        }

        result = redact_pii(None, None, event_dict)

        # All emails should be redacted
        assert "[EMAIL]" in result["event"]
        assert "test@example.com" not in result["event"]
        assert "admin@example.com" not in result["event"]
        assert "user2@test.org" not in result["event"]

    def test_redact_pii_with_api_keys(self):
        """Test PII redaction with various API key formats."""
        from structlog.types import EventDict

        test_cases = [
            "sk-1234567890abcdef",
            "AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        ]

        for api_key in test_cases:
            event_dict: EventDict = {"event": f"API key: {api_key}"}
            result = redact_pii(None, None, event_dict)

            assert "[REDACTED]" in result["event"]
            assert api_key not in result["event"]

    def test_redact_pii_with_phone_numbers(self):
        """Test PII redaction with various phone number formats."""
        from structlog.types import EventDict

        phone_numbers = ["123-456-7890", "123.456.7890", "1234567890"]

        for phone in phone_numbers:
            event_dict: EventDict = {"event": f"Call {phone} for support"}
            result = redact_pii(None, None, event_dict)

            assert "[PHONE]" in result["event"]
            assert phone not in result["event"]

    def test_redact_pii_with_mixed_pii(self):
        """Test PII redaction with multiple PII types in one message."""
        from structlog.types import EventDict

        event_dict: EventDict = {
            "event": "Contact user@example.com at 123-456-7890 using key sk-abcdef123456"
        }

        result = redact_pii(None, None, event_dict)

        assert "[EMAIL]" in result["event"]
        assert "[PHONE]" in result["event"]
        assert "[REDACTED]" in result["event"]
        assert "user@example.com" not in result["event"]
        assert "123-456-7890" not in result["event"]
        assert "sk-abcdef123456" not in result["event"]

    def test_redact_pii_with_non_string_event(self):
        """Test PII redaction when event is not a string."""
        from structlog.types import EventDict

        # Event is a dict
        event_dict: EventDict = {"event": {"key": "value"}}
        result = redact_pii(None, None, event_dict)
        assert result["event"] == {"key": "value"}

        # Event is a number
        event_dict = {"event": 12345}
        result = redact_pii(None, None, event_dict)
        assert result["event"] == 12345

        # Event is None
        event_dict = {"event": None}
        result = redact_pii(None, None, event_dict)
        assert result["event"] is None

    def test_redact_pii_with_empty_event(self):
        """Test PII redaction with empty event."""
        from structlog.types import EventDict

        event_dict: EventDict = {"event": ""}
        result = redact_pii(None, None, event_dict)
        assert result["event"] == ""

    def test_redact_pii_preserves_other_fields(self):
        """Test that PII redaction doesn't affect other fields."""
        from structlog.types import EventDict

        event_dict: EventDict = {
            "event": "Email: test@example.com",
            "user_id": "user-123",
            "timestamp": "2025-12-06T12:00:00Z",
            "level": "info",
        }

        result = redact_pii(None, None, event_dict)

        assert result["user_id"] == "user-123"
        assert result["timestamp"] == "2025-12-06T12:00:00Z"
        assert result["level"] == "info"


@pytest.mark.unit
class TestThreadContextEdgeCases:
    """Test edge cases for thread context management."""

    def test_add_thread_id_processor_with_no_context(self):
        """Test add_thread_id processor when no thread ID is set."""
        from structlog.types import EventDict

        clear_thread_id()  # Ensure no thread ID

        event_dict: EventDict = {"event": "test"}
        result = add_thread_id(None, None, event_dict)

        # Should not add thread_id field
        assert "thread_id" not in result

    def test_add_thread_id_processor_with_context(self):
        """Test add_thread_id processor when thread ID is set."""
        from structlog.types import EventDict

        set_thread_id("test-thread-123")

        event_dict: EventDict = {"event": "test"}
        result = add_thread_id(None, None, event_dict)

        assert result["thread_id"] == "test-thread-123"

        clear_thread_id()

    def test_add_timestamp_processor(self):
        """Test add_timestamp processor adds ISO timestamp."""
        from datetime import datetime

        from structlog.types import EventDict

        event_dict: EventDict = {"event": "test"}
        result = add_timestamp(None, None, event_dict)

        assert "timestamp" in result
        assert result["timestamp"].endswith("Z")

        # Verify it's a valid ISO timestamp
        timestamp_str = result["timestamp"][:-1]  # Remove 'Z'
        datetime.fromisoformat(timestamp_str)

    def test_concurrent_thread_contexts(self):
        """Test that thread contexts don't interfere with each other."""
        import threading
        import time

        results = {}

        def thread_func(thread_name):
            set_thread_id(thread_name)
            time.sleep(0.01)  # Small delay
            from src.core.logging.logger import get_thread_id

            results[thread_name] = get_thread_id()
            clear_thread_id()

        threads = [threading.Thread(target=thread_func, args=(f"thread-{i}",)) for i in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Each thread should have seen its own thread ID
        for i in range(5):
            thread_name = f"thread-{i}"
            assert results[thread_name] == thread_name


@pytest.mark.unit
class TestLoggerConfigurationEdgeCases:
    """Test edge cases for logger configuration."""

    def test_logger_with_all_log_levels(self):
        """Test logger supports all standard log levels."""
        logger = get_logger("test")

        levels = ["debug", "info", "warning", "error", "critical"]

        for level in levels:
            assert hasattr(logger, level)
            method = getattr(logger, level)
            assert callable(method)

    def test_logger_with_exception_info(self):
        """Test logger can log exception information."""
        logger = get_logger("test")

        try:
            raise ValueError("Test exception")
        except ValueError:
            # Should not raise
            with patch.object(logger, "error") as mock_error:
                logger.error("Exception occurred", exc_info=True)
                mock_error.assert_called_once()

    def test_logger_with_stack_info(self):
        """Test logger can log stack information."""
        logger = get_logger("test")

        with patch.object(logger, "info") as mock_info:
            logger.info("Stack trace", stack_info=True)
            mock_info.assert_called_once()

    def test_log_stage_with_all_levels(self):
        """Test log_stage works with all log levels."""
        logger = get_logger("test")

        levels = ["debug", "info", "warning", "error", "critical"]

        for level in levels:
            with patch.object(logger, level) as mock_level:
                log_stage(logger, "1", f"Test {level}", level=level)
                mock_level.assert_called_once()
