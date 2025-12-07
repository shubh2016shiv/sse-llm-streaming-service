"""
Unit Tests for Configuration Constants

Tests the configuration constants and their validation.
"""

import pytest

from src.core.config.constants import (
    L1_CACHE_MAX_SIZE,
    MAX_RETRIES,
    REDIS_KEY_CACHE_RESPONSE,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    SSE_EVENT_CHUNK,
    SSE_EVENT_COMPLETE,
    SSE_EVENT_ERROR,
    SSE_EVENT_STATUS,
    SSE_HEARTBEAT_INTERVAL,
    CircuitState,
)


@pytest.mark.unit
class TestSSEConstants:
    """Test SSE event constants."""

    def test_sse_event_types_are_strings(self):
        """Test that all SSE event types are strings."""
        events = [SSE_EVENT_CHUNK, SSE_EVENT_COMPLETE, SSE_EVENT_ERROR, SSE_EVENT_STATUS]

        for event in events:
            assert isinstance(event, str)
            assert len(event) > 0

    def test_sse_event_types_are_unique(self):
        """Test that all SSE event types are unique."""
        events = [SSE_EVENT_CHUNK, SSE_EVENT_COMPLETE, SSE_EVENT_ERROR, SSE_EVENT_STATUS]

        assert len(set(events)) == len(events)

    def test_sse_heartbeat_interval_is_positive(self):
        """Test that heartbeat interval is a positive number."""
        assert isinstance(SSE_HEARTBEAT_INTERVAL, int | float)
        assert SSE_HEARTBEAT_INTERVAL > 0


@pytest.mark.unit
class TestRetryConstants:
    """Test retry-related constants."""

    def test_retry_constants_are_positive(self):
        """Test that retry constants have valid values."""
        assert isinstance(MAX_RETRIES, int)
        assert MAX_RETRIES > 0

        assert isinstance(RETRY_BASE_DELAY, int | float)
        assert RETRY_BASE_DELAY > 0

        assert isinstance(RETRY_MAX_DELAY, int | float)
        assert RETRY_MAX_DELAY > RETRY_BASE_DELAY

    def test_retry_delays_form_progression(self):
        """Test that retry delays form a valid exponential progression."""
        assert RETRY_MAX_DELAY >= RETRY_BASE_DELAY


@pytest.mark.unit
class TestCircuitBreakerConstants:
    """Test circuit breaker state enum."""

    def test_circuit_state_enum_values(self):
        """Test that CircuitState enum has expected values."""
        assert hasattr(CircuitState, "CLOSED")
        assert hasattr(CircuitState, "OPEN")
        assert hasattr(CircuitState, "HALF_OPEN")

    def test_circuit_state_values_are_strings(self):
        """Test that CircuitState values are strings."""
        for state in CircuitState:
            assert isinstance(state.value, str)
            assert len(state.value) > 0

    def test_circuit_state_values_are_unique(self):
        """Test that CircuitState values are unique."""
        values = [state.value for state in CircuitState]
        assert len(set(values)) == len(values)


@pytest.mark.unit
class TestCacheConstants:
    """Test cache-related constants."""

    def test_cache_constants_have_valid_values(self):
        """Test that cache constants have reasonable values."""
        assert isinstance(L1_CACHE_MAX_SIZE, int)
        assert L1_CACHE_MAX_SIZE > 0
        assert L1_CACHE_MAX_SIZE <= 10000  # Reasonable upper bound

    def test_redis_key_prefix_is_string(self):
        """Test that Redis key prefix is a valid string."""
        assert isinstance(REDIS_KEY_CACHE_RESPONSE, str)
        assert len(REDIS_KEY_CACHE_RESPONSE) > 0
        assert ":" in REDIS_KEY_CACHE_RESPONSE  # Should contain namespace separator

    def test_redis_key_format_is_consistent(self):
        """Test that Redis key format follows expected pattern."""
        # Should be in format "namespace:category"
        parts = REDIS_KEY_CACHE_RESPONSE.split(":")
        assert len(parts) >= 2
        assert all(len(part) > 0 for part in parts)
