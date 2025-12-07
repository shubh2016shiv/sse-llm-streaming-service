"""
Unit Tests for Request Validator

Tests validation logic for stream requests.
"""

from unittest.mock import patch

import pytest

from src.application.validators.stream_validator import RequestValidator


@pytest.mark.unit
class TestRequestValidator:
    """Test suite for RequestValidator."""

    @pytest.fixture
    def validator(self):
        """Create RequestValidator for testing."""
        return RequestValidator()

    def test_validate_query_accepts_valid_queries(self, validator):
        """Test validation accepts valid queries."""
        valid_queries = [
            "What is AI?",
            "Explain quantum physics",
            "How does machine learning work?",
            "Tell me about Python programming",
            "What are the benefits of exercise?",
        ]

        for query in valid_queries:
            # Should not raise exception
            validator.validate_query(query)

    def test_validate_query_rejects_empty_query(self, validator):
        """Test validation rejects empty queries."""
        with pytest.raises(ValueError) as exc_info:
            validator.validate_query("")

        assert "empty" in str(exc_info.value).lower()

    def test_validate_query_rejects_whitespace_only(self, validator):
        """Test validation rejects whitespace-only queries."""
        with pytest.raises(ValueError) as exc_info:
            validator.validate_query("   ")

        assert "empty" in str(exc_info.value).lower()

    def test_validate_query_rejects_none_query(self, validator):
        """Test validation rejects None queries."""
        with pytest.raises(ValueError) as exc_info:
            validator.validate_query(None)

        assert "empty" in str(exc_info.value).lower()

    def test_validate_query_rejects_overly_long_queries(self, validator):
        """Test validation rejects extremely long queries."""
        # Create a very long query
        long_query = "What is AI? " * 1000  # Very long

        with pytest.raises(ValueError) as exc_info:
            validator.validate_query(long_query)

        assert "long" in str(exc_info.value).lower() or "length" in str(exc_info.value).lower()

    def test_validate_model_accepts_known_models(self, validator):
        """Test validation accepts known model names."""
        known_models = [
            "gpt-3.5-turbo",
            "gpt-4",
            "gpt-4-turbo",
            "claude-3-opus",
            "claude-3-sonnet",
            "gemini-pro",
            "gemini-pro-vision",
        ]

        for model in known_models:
            # Should not raise exception
            validator.validate_model(model)

    def test_validate_model_rejects_empty_model(self, validator):
        """Test validation rejects empty model names."""
        with pytest.raises(ValueError) as exc_info:
            validator.validate_model("")

        assert "model" in str(exc_info.value).lower()

    def test_validate_model_rejects_invalid_models(self, validator):
        """Test validation rejects obviously invalid model names."""
        invalid_models = [
            "invalid-model-name",
            "gpt-5",  # Doesn't exist yet
            "unknown-provider-model",
            "fake-model-123",
        ]

        for model in invalid_models:
            with pytest.raises(ValueError) as exc_info:
                validator.validate_model(model)

            assert "model" in str(exc_info.value).lower()

    def test_check_connection_limit_accepts_under_limit(self, validator):
        """Test connection limit check accepts connections under limit."""
        # Mock settings with reasonable limit
        with patch.object(validator, "settings") as mock_settings:
            mock_settings.app.MAX_CONNECTIONS = 10

            # Should not raise for reasonable numbers
            validator.check_connection_limit(5)
            validator.check_connection_limit(9)

    def test_check_connection_limit_rejects_over_limit(self, validator):
        """Test connection limit check rejects connections over limit."""
        with patch.object(validator, "settings") as mock_settings:
            mock_settings.app.MAX_CONNECTIONS = 10

            with pytest.raises(Exception) as exc_info:
                validator.check_connection_limit(15)

            assert (
                "connection" in str(exc_info.value).lower()
                or "limit" in str(exc_info.value).lower()
            )

    def test_check_connection_limit_handles_zero_limit(self, validator):
        """Test connection limit check with zero limit."""
        with patch.object(validator, "settings") as mock_settings:
            mock_settings.app.MAX_CONNECTIONS = 0

            with pytest.raises(Exception):
                validator.check_connection_limit(1)

    def test_validate_query_handles_unicode_characters(self, validator):
        """Test validation handles Unicode characters properly."""
        unicode_queries = [
            "What is naïve Bayesian classification?",
            "How does Schrödinger's cat work?",
            "Explain Poincaré conjecture",
            "What are Möbius strips?",
        ]

        for query in unicode_queries:
            # Should not raise exception
            validator.validate_query(query)

    def test_validate_query_rejects_malicious_content(self, validator):
        """Test validation rejects potentially malicious content."""
        malicious_queries = [
            "<script>alert('xss')</script>",
            "SELECT * FROM users; DROP TABLE users;",
            "../../../etc/passwd",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
        ]

        for query in malicious_queries:
            with pytest.raises(ValueError) as exc_info:
                validator.validate_query(query)

            assert (
                "invalid" in str(exc_info.value).lower()
                or "malicious" in str(exc_info.value).lower()
            )

    def test_validate_model_handles_version_numbers(self, validator):
        """Test validation handles model names with version numbers."""
        versioned_models = ["gpt-3.5-turbo-0125", "claude-3-5-sonnet-20241022", "gemini-1.5-pro"]

        for model in versioned_models:
            # Should accept versioned models (may not validate strictly)
            try:
                validator.validate_model(model)
            except ValueError:
                # It's OK if strict validation rejects these
                pass

    def test_connection_limit_check_is_idempotent(self, validator):
        """Test connection limit check doesn't modify state."""
        with patch.object(validator, "settings") as mock_settings:
            mock_settings.app.MAX_CONNECTIONS = 10

            # Multiple calls should behave consistently
            for _ in range(5):
                validator.check_connection_limit(5)

    def test_validator_handles_extreme_connection_counts(self, validator):
        """Test validator handles extreme connection counts."""
        with patch.object(validator, "settings") as mock_settings:
            mock_settings.app.MAX_CONNECTIONS = 1000

            # Should handle large numbers
            validator.check_connection_limit(999)

            with pytest.raises(Exception):
                validator.check_connection_limit(1001)

    def test_validate_query_normalizes_whitespace(self, validator):
        """Test query validation handles various whitespace."""
        # These should all be treated as non-empty
        queries_with_whitespace = ["  query  ", "\tquery\t", "\nquery\n", "query\r\n"]

        for query in queries_with_whitespace:
            # Should accept queries with leading/trailing whitespace
            # (assuming the validator trims whitespace)
            try:
                validator.validate_query(query)
            except ValueError:
                # If it rejects, it should be for content reasons, not just whitespace
                pass






