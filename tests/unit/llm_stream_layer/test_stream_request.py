"""
Unit Tests for StreamRequest Model

Tests StreamRequest data model and invariants.
"""

import pytest

from src.llm_stream.models.stream_request import SSEEvent, StreamRequest


@pytest.mark.unit
class TestStreamRequest:
    """Test suite for StreamRequest model."""

    def test_stream_request_creation(self):
        """Test StreamRequest can be created with valid parameters."""
        request = StreamRequest(
            query="What is AI?",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        assert request.query == "What is AI?"
        assert request.model == "gpt-3.5-turbo"
        assert request.provider == "openai"
        assert request.thread_id == "thread-123"
        assert request.user_id == "user-456"

    def test_stream_request_optional_provider(self):
        """Test StreamRequest with optional provider."""
        request = StreamRequest(
            query="Test query",
            model="gpt-4",
            thread_id="thread-123",
            user_id="user-456",
            # provider is optional
        )

        assert request.provider is None
        assert request.query == "Test query"
        assert request.model == "gpt-4"

    def test_stream_request_validation(self):
        """Test StreamRequest validates required fields."""
        # Should require query
        with pytest.raises(ValueError):
            StreamRequest(
                query="",  # Empty query should be rejected
                model="gpt-3.5-turbo",
                provider="openai",
                thread_id="thread-123",
                user_id="user-456",
            )

    def test_stream_request_equality(self):
        """Test StreamRequest equality comparison."""
        request1 = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        request2 = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        request3 = StreamRequest(
            query="Different",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        assert request1 == request2
        assert request1 != request3

    def test_stream_request_hash_consistency(self):
        """Test StreamRequest hash is consistent for same data."""
        request1 = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        request2 = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        # Same data should have same hash
        assert hash(request1) == hash(request2)

    def test_stream_request_string_representation(self):
        """Test StreamRequest string representation."""
        request = StreamRequest(
            query="What is AI?",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        str_repr = str(request)

        assert "What is AI?" in str_repr
        assert "gpt-3.5-turbo" in str_repr
        assert "openai" in str_repr
        assert "thread-123" in str_repr

    def test_stream_request_immutable_after_creation(self):
        """Test StreamRequest fields cannot be modified after creation."""
        request = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        # Attempt to modify (should fail or be prevented)
        with pytest.raises((AttributeError, TypeError)):
            request.query = "Modified query"

    def test_stream_request_handles_unicode(self):
        """Test StreamRequest handles Unicode characters."""
        request = StreamRequest(
            query="What is naïve AI?",
            model="gpt-4",
            provider="openai",
            thread_id="thread-café",
            user_id="user-tëst",
        )

        assert request.query == "What is naïve AI?"
        assert request.thread_id == "thread-café"
        assert request.user_id == "user-tëst"

    def test_stream_request_field_types(self):
        """Test StreamRequest enforces correct field types."""
        # All string fields should be strings
        request = StreamRequest(
            query="Test",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="thread-123",
            user_id="user-456",
        )

        assert isinstance(request.query, str)
        assert isinstance(request.model, str)
        assert isinstance(request.provider, str | None)
        assert isinstance(request.thread_id, str)
        assert isinstance(request.user_id, str)


@pytest.mark.unit
class TestSSEEvent:
    """Test suite for SSEEvent model."""

    def test_sse_event_creation(self):
        """Test SSEEvent can be created."""
        event = SSEEvent(event="chunk", data={"content": "Hello", "chunk_index": 1})

        assert event.event == "chunk"
        assert event.data == {"content": "Hello", "chunk_index": 1}

    def test_sse_event_with_string_data(self):
        """Test SSEEvent with string data."""
        event = SSEEvent(event="status", data="Validation completed")

        assert event.event == "status"
        assert event.data == "Validation completed"

    def test_sse_event_with_complex_data(self):
        """Test SSEEvent with complex data structures."""
        data = {
            "thread_id": "thread-123",
            "chunk_count": 5,
            "total_length": 150,
            "duration_ms": 250,
            "cached": False,
        }

        event = SSEEvent(event="complete", data=data)

        assert event.event == "complete"
        assert event.data["thread_id"] == "thread-123"
        assert event.data["chunk_count"] == 5
        assert event.data["cached"] is False

    def test_sse_event_equality(self):
        """Test SSEEvent equality."""
        event1 = SSEEvent(event="chunk", data={"content": "test"})
        event2 = SSEEvent(event="chunk", data={"content": "test"})
        event3 = SSEEvent(event="chunk", data={"content": "different"})

        assert event1 == event2
        assert event1 != event3

    def test_sse_event_string_representation(self):
        """Test SSEEvent string representation."""
        event = SSEEvent(event="error", data={"message": "Test error"})

        str_repr = str(event)

        assert "error" in str_repr
        assert "Test error" in str_repr

    def test_sse_event_data_immutability(self):
        """Test SSEEvent data is handled correctly."""
        data = {"key": "value"}
        event = SSEEvent(event="test", data=data)

        # Modifying original dict should not affect event
        data["new_key"] = "new_value"
        assert "new_key" not in event.data

    def test_sse_event_standard_event_types(self):
        """Test SSEEvent with standard event types."""
        standard_events = ["status", "chunk", "error", "complete", "heartbeat"]

        for event_type in standard_events:
            event = SSEEvent(event=event_type, data="test data")
            assert event.event == event_type
            assert event.data == "test data"

    def test_sse_event_data_types(self):
        """Test SSEEvent accepts various data types."""
        test_cases = ["string data", {"dict": "data"}, ["list", "data"], 42, True, None]

        for data in test_cases:
            event = SSEEvent(event="test", data=data)
            assert event.data == data

    def test_sse_event_empty_data(self):
        """Test SSEEvent with empty data."""
        event = SSEEvent(event="test", data={})

        assert event.event == "test"
        assert event.data == {}

    def test_sse_event_data_validation(self):
        """Test SSEEvent data validation."""
        # Should accept various data types without strict validation
        # (Pydantic will handle type validation if configured)

        event = SSEEvent(event="test", data="valid data")
        assert event.data == "valid data"
