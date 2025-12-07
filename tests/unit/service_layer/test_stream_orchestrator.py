"""
Unit Tests for StreamOrchestrator

Tests the complete request lifecycle orchestration with mocked dependencies.
Demonstrates proper dependency injection testing patterns.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm_stream.providers.base_provider import StreamChunk
from src.llm_stream.services.stream_orchestrator import StreamOrchestrator


@pytest.mark.unit
class TestStreamOrchestrator:
    """
    Test suite for StreamOrchestrator service layer.

    These tests verify the request lifecycle orchestration logic
    with all dependencies properly mocked.
    """

    @pytest.fixture
    def orchestrator(
        self,
        mock_cache_manager,
        mock_provider_factory,
        mock_execution_tracker,
        mock_settings,
        mock_request_validator,
    ):
        """Create StreamOrchestrator with all mocked dependencies."""
        return StreamOrchestrator(
            cache_manager=mock_cache_manager,
            provider_factory=mock_provider_factory,
            execution_tracker=mock_execution_tracker,
            settings=mock_settings,
            validator=mock_request_validator,
        )

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_response_immediately(
        self, orchestrator, sample_stream_request, mock_cache_manager
    ):
        """
        Test that cached responses are returned without calling LLM provider.

        This verifies the L1/L2 cache hit optimization path.
        """
        # Arrange
        cached_response = "The capital of France is Paris."
        mock_cache_manager.get = AsyncMock(return_value=cached_response)

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        assert len(events) == 3  # status, chunk, complete
        assert events[0].event == "status"
        assert events[1].event == "chunk"
        assert events[1].data["content"] == cached_response
        assert events[1].data["cached"] is True
        assert events[2].event == "complete"
        assert events[2].data["cached"] is True

    @pytest.mark.asyncio
    async def test_cache_miss_triggers_llm_provider_call(
        self,
        orchestrator,
        sample_stream_request,
        mock_cache_manager,
        mock_provider_factory,
        sample_stream_chunks,
    ):
        """
        Test that cache miss triggers LLM provider and caches result.

        This verifies the complete request flow: cache miss → LLM → cache set.
        """
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        mock_provider = mock_provider_factory.get_healthy_provider.return_value

        async def mock_stream(*args, **kwargs):
            for chunk in sample_stream_chunks:
                yield chunk

        mock_provider.stream = mock_stream

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert - verify chunks were streamed
        chunk_events = [e for e in events if e.event == "chunk"]
        assert len(chunk_events) == len(sample_stream_chunks)

        # Assert - verify cache was set with full response
        mock_cache_manager.set.assert_called_once()
        cached_content = mock_cache_manager.set.call_args[0][1]
        assert "Paris" in cached_content

    @pytest.mark.skip(
        reason=(
            "TODO: Fix provider failure simulation - "
            "mock_provider_factory.get_healthy_provider returns mock instead of None"
        )
    )
    async def test_all_providers_down_returns_error_event(
        self, orchestrator, sample_stream_request, mock_cache_manager, mock_provider_factory
    ):
        """
        Test that AllProvidersDownError is handled gracefully.

        This verifies error handling when no healthy providers are available.
        """
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)
        # Make get_healthy_provider return None to simulate no providers available
        mock_provider_factory.get_healthy_provider.return_value = None

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        error_events = [e for e in events if e.event == "error"]
        assert len(error_events) > 0
        assert "AllProvidersDownError" in error_events[0].data.get("error", "")

    @pytest.mark.asyncio
    async def test_active_connections_incremented_and_decremented(
        self, orchestrator, sample_stream_request, mock_cache_manager
    ):
        """
        Test that active connections counter is properly managed.

        This verifies resource tracking for connection limits.
        """
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value="cached")
        initial_count = orchestrator.active_connections

        # Act
        async for _ in orchestrator.stream(sample_stream_request):
            pass

        # Assert
        final_count = orchestrator.active_connections
        assert final_count == initial_count  # Should return to initial

    def test_get_stats_returns_expected_structure(self, orchestrator):
        """
        Test that get_stats returns correct statistics structure.

        This verifies the monitoring/observability interface.
        """
        # Act
        stats = orchestrator.get_stats()

        # Assert
        assert "active_connections" in stats
        assert "initialized" in stats
        assert "cache_stats" in stats
        assert stats["initialized"] is True
        assert isinstance(stats["active_connections"], int)

    @pytest.mark.asyncio
    async def test_execution_tracker_called_for_all_stages(
        self, orchestrator, sample_stream_request, mock_cache_manager, mock_execution_tracker
    ):
        """
        Test that execution tracker records all processing stages.

        This verifies observability integration.
        """
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value="cached")

        # Act
        async for _ in orchestrator.stream(sample_stream_request):
            pass

        # Assert - verify stages were tracked
        assert mock_execution_tracker.track_stage.called
        assert mock_execution_tracker.clear_thread_data.called

    @pytest.mark.asyncio
    async def test_validation_failure_returns_error_event(
        self, orchestrator, mock_request_validator, sample_stream_request
    ):
        """Test that validation failures return appropriate error events."""
        # Arrange
        mock_request_validator.validate_query.side_effect = ValueError("Invalid query")

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        assert len(events) == 1
        assert events[0].event == "error"
        assert events[0].data["error"] == "ValueError"
        assert "Invalid query" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_connection_limit_exceeded_returns_error(
        self, orchestrator, mock_request_validator, sample_stream_request
    ):
        """Test connection limit enforcement."""
        # Arrange
        orchestrator._active_connections = orchestrator.settings.app.MAX_CONNECTIONS
        mock_request_validator.check_connection_limit.side_effect = Exception(
            "Connection limit exceeded"
        )

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        assert len(events) == 1
        assert events[0].event == "error"
        assert "Connection limit exceeded" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_provider_selection_failure_returns_error(
        self, orchestrator, sample_stream_request, mock_cache_manager, mock_provider_factory
    ):
        """Test provider selection failure handling."""

        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)
        mock_provider_factory.get_healthy_provider.return_value = None

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        assert len(events) == 1
        assert events[0].event == "error"
        assert events[0].data["error"] == "AllProvidersDownError"

    @pytest.mark.asyncio
    async def test_provider_circuit_open_fallback(
        self,
        orchestrator,
        sample_stream_request,
        mock_cache_manager,
        mock_provider_factory,
        sample_stream_chunks,
    ):
        """Test fallback to healthy provider when preferred provider has open circuit."""
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        preferred_provider = MagicMock()
        preferred_provider.get_circuit_state.return_value = "open"  # Circuit open

        healthy_provider = AsyncMock()

        async def mock_stream(*args, **kwargs):
            for chunk in sample_stream_chunks:
                yield chunk

        healthy_provider.stream = mock_stream
        healthy_provider.name = "fallback-provider"

        mock_provider_factory.get.return_value = preferred_provider
        mock_provider_factory.get_healthy_provider.return_value = healthy_provider

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert - should use fallback provider
        assert len(events) > 2  # status, chunks, complete
        assert events[0].event == "status"
        # Verify fallback provider was used
        mock_provider_factory.get_healthy_provider.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_content_chunks_are_handled(
        self,
        orchestrator,
        sample_stream_request,
        mock_cache_manager,
        mock_provider_factory,
        empty_stream_chunks,
    ):
        """Test handling of empty content chunks."""
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        mock_provider = mock_provider_factory.get_healthy_provider.return_value

        async def mock_stream(*args, **kwargs):
            for chunk in empty_stream_chunks:
                yield chunk

        mock_provider.stream = mock_stream

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert - should handle empty content gracefully
        chunk_events = [e for e in events if e.event == "chunk"]
        assert len(chunk_events) == 0  # No chunks with content

        complete_event = next(e for e in events if e.event == "complete")
        assert complete_event.data["total_length"] == 0

    @pytest.mark.asyncio
    async def test_early_finish_reason_stops_streaming(
        self, orchestrator, sample_stream_request, mock_cache_manager, mock_provider_factory
    ):
        """Test that early finish_reason stops streaming immediately."""

        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        early_chunks = [
            StreamChunk(content="Early", finish_reason=None),
            StreamChunk(content=" stop", finish_reason="stop"),  # Early finish
            StreamChunk(content=" ignored", finish_reason=None),  # Should be ignored
        ]

        mock_provider = mock_provider_factory.get_healthy_provider.return_value

        async def mock_stream(*args, **kwargs):
            for chunk in early_chunks:
                yield chunk

        mock_provider.stream = mock_stream

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert - should stop at finish_reason
        chunk_events = [e for e in events if e.event == "chunk"]
        assert len(chunk_events) == 2  # Only chunks before finish_reason
        assert "Early stop" in "".join([e.data["content"] for e in chunk_events])

    @pytest.mark.asyncio
    async def test_heartbeat_cancellation_on_error(
        self, orchestrator, sample_stream_request, mock_cache_manager, mock_provider_factory
    ):
        """Test heartbeat task is cancelled when provider fails."""
        import asyncio

        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        mock_provider = mock_provider_factory.get_healthy_provider.return_value

        async def failing_stream(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simulate some work
            raise Exception("Provider failed")

        mock_provider.stream = failing_stream

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert - should have error event, heartbeat should be cancelled
        assert len(events) == 1
        assert events[0].event == "error"
        assert "Provider failed" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_active_connections_tracking(
        self, orchestrator, sample_stream_request, mock_cache_manager
    ):
        """Test active connections are properly tracked."""
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value="cached")  # Immediate return

        initial_connections = orchestrator.active_connections

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)
            # Check connections during streaming
            assert orchestrator.active_connections >= initial_connections

        # Assert - connections should be decremented after completion
        final_connections = orchestrator.active_connections
        assert final_connections == initial_connections

    @pytest.mark.asyncio
    async def test_stats_reporting_includes_performance_data(
        self,
        orchestrator,
        sample_stream_request,
        mock_cache_manager,
        mock_provider_factory,
        sample_stream_chunks,
        mock_execution_tracker,
    ):
        """Test complete event includes comprehensive stats."""
        # Arrange
        mock_cache_manager.get = AsyncMock(return_value=None)

        mock_provider = mock_provider_factory.get_healthy_provider.return_value

        async def mock_stream(*args, **kwargs):
            for chunk in sample_stream_chunks:
                yield chunk

        mock_provider.stream = mock_stream

        mock_execution_tracker.get_execution_summary.return_value = {
            "total_duration_ms": 150,
            "stages": [],
        }

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        complete_event = next(e for e in events if e.event == "complete")
        stats = complete_event.data

        assert "thread_id" in stats
        assert "chunk_count" in stats
        assert "total_length" in stats
        assert "duration_ms" in stats
        assert stats["duration_ms"] == 150

    @pytest.mark.asyncio
    async def test_unexpected_exceptions_are_caught(
        self, orchestrator, sample_stream_request, mock_cache_manager
    ):
        """Test that unexpected exceptions are caught and returned as errors."""
        # Arrange - force an unexpected exception
        mock_cache_manager.get = AsyncMock(side_effect=Exception("Unexpected error"))

        # Act
        events = []
        async for event in orchestrator.stream(sample_stream_request):
            events.append(event)

        # Assert
        assert len(events) == 1
        assert events[0].event == "error"
        assert events[0].data["error"] == "internal_error"
        assert "Unexpected error" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_thread_id_context_management(
        self, orchestrator, sample_stream_request, mock_cache_manager
    ):
        """Test thread ID context is properly managed."""
        from src.core.logging.logger import get_thread_id

        # Arrange
        mock_cache_manager.get = AsyncMock(return_value="cached")

        # Act & Assert
        async for event in orchestrator.stream(sample_stream_request):
            # During streaming, thread ID should be set
            current_thread_id = get_thread_id()
            assert current_thread_id == sample_stream_request.thread_id
            break  # Just check first event

    @pytest.mark.asyncio
    async def test_get_stats_returns_active_connections(self, orchestrator):
        """Test get_stats returns current state."""
        # Arrange
        orchestrator._active_connections = 3
        orchestrator._initialized = True

        # Act
        stats = orchestrator.get_stats()

        # Assert
        assert stats["active_connections"] == 3
        assert stats["initialized"] is True
        assert "cache_stats" in stats
