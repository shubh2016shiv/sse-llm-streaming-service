"""
Unit Tests for ExecutionTracker

Tests the hash-based sampling algorithm and execution tracking functionality.
Validates statistical properties and deterministic behavior.
"""

from unittest.mock import patch

import pytest

from src.core.observability.execution_tracker import ExecutionTracker


@pytest.mark.unit
class TestExecutionTrackerSampling:
    """
    Test suite for ExecutionTracker sampling algorithm.

    These tests verify the hash-based sampling implementation
    documented in ADR-003.
    """

    @pytest.fixture
    def tracker(self, mock_settings):
        """Create ExecutionTracker with mocked settings."""
        # Patch locally in the fixture
        with patch(
            "src.core.observability.execution_tracker.get_settings", return_value=mock_settings
        ):
            return ExecutionTracker()

    def test_should_track_is_deterministic_for_same_thread_id(self, tracker):
        # ... existing code ...
        """
        Test that same thread_id always produces same tracking decision.

        This is critical for consistent trace collection - if we track
        stage 1, we must track ALL stages for that request.
        """
        thread_id = "test-thread-abc-123"

        # Call multiple times with same thread_id
        results = [tracker.should_track(thread_id) for _ in range(10)]

        # All results must be identical
        assert len(set(results)) == 1, "Same thread_id must always return same decision"

    def test_should_track_distribution_approximates_sample_rate(self, tracker):
        """
        Test that sampling rate is statistically correct.

        With 10% sample rate and 10,000 samples, we expect ~1,000 tracked
        (within reasonable margin of error).
        """
        sample_size = 10000
        tracked_count = sum(1 for i in range(sample_size) if tracker.should_track(f"thread-{i}"))

        actual_rate = tracked_count / sample_size

        # Should be within 2% of target (8% - 12%)
        assert 0.08 <= actual_rate <= 0.12, (
            f"Sample rate {actual_rate:.2%} outside acceptable range"
        )

    def test_sample_rate_100_percent_tracks_everything(self, mock_settings):
        """
        Test edge case: 100% sample rate tracks all requests.
        """
        with patch(
            "src.core.observability.execution_tracker.get_settings", return_value=mock_settings
        ):
            tracker = ExecutionTracker()
            tracker._sample_rate = 1.0

            results = [tracker.should_track(f"thread-{i}") for i in range(100)]

            assert all(results), "100% sample rate must track everything"

    def test_sample_rate_0_percent_tracks_nothing(self, mock_settings):
        """
        Test edge case: 0% sample rate tracks no requests.
        """
        with patch(
            "src.core.observability.execution_tracker.get_settings", return_value=mock_settings
        ):
            tracker = ExecutionTracker()
            tracker._sample_rate = 0.0

            results = [tracker.should_track(f"thread-{i}") for i in range(100)]

            assert not any(results), "0% sample rate must track nothing"


@pytest.mark.unit
class TestExecutionTrackerStageTracking:
    """
    Test suite for execution stage tracking functionality.
    """

    @pytest.fixture
    def tracker(self, mock_settings):
        """Create ExecutionTracker with 100% sample rate."""
        with patch(
            "src.core.observability.execution_tracker.get_settings", return_value=mock_settings
        ):
            tracker = ExecutionTracker()
            tracker._sample_rate = 1.0
            return tracker

    def test_track_stage_creates_execution_record(self, tracker):
        """
        Test that track_stage creates proper execution records.
        """
        thread_id = "test-thread"

        with tracker.track_stage("1", "Validation", thread_id):
            pass

        summary = tracker.get_execution_summary(thread_id)

        assert "stages" in summary
        assert len(summary["stages"]) > 0
        assert summary["stages"][0]["stage_id"] == "1"
        assert summary["stages"][0]["stage_name"] == "Validation"

    def test_track_stage_records_duration(self, tracker):
        """
        Test that stage duration is recorded.
        """
        import time

        thread_id = "test-thread"

        with tracker.track_stage("1", "Test Stage", thread_id):
            time.sleep(0.01)  # Sleep 10ms

        summary = tracker.get_execution_summary(thread_id)
        stage = summary["stages"][0]

        assert "duration_ms" in stage
        assert stage["duration_ms"] >= 10  # At least 10ms

    def test_clear_thread_data_removes_all_records(self, tracker):
        """
        Test that clear_thread_data properly cleans up memory.

        This is important for preventing memory leaks.
        """
        thread_id = "test-thread"

        # Create some data
        with tracker.track_stage("1", "Stage 1", thread_id):
            pass
        with tracker.track_stage("2", "Stage 2", thread_id):
            pass

        # Verify data exists
        summary_before = tracker.get_execution_summary(thread_id)
        assert len(summary_before.get("stages", [])) == 2

        # Clear data
        tracker.clear_thread_data(thread_id)

        # Verify data is gone
        summary_after = tracker.get_execution_summary(thread_id)
        assert len(summary_after.get("stages", [])) == 0

    def test_multiple_threads_tracked_independently(self, tracker):
        """
        Test that different threads are tracked independently.
        """
        thread_1 = "thread-1"
        thread_2 = "thread-2"

        with tracker.track_stage("1", "Stage A", thread_1):
            pass

        with tracker.track_stage("1", "Stage B", thread_2):
            pass

        summary_1 = tracker.get_execution_summary(thread_1)
        summary_2 = tracker.get_execution_summary(thread_2)

        assert summary_1["stages"][0]["stage_name"] == "Stage A"
        assert summary_2["stages"][0]["stage_name"] == "Stage B"

    def test_nested_stage_tracking(self, tracker):
        """Test that nested stages are tracked correctly."""
        thread_id = "nested-thread"

        with tracker.track_stage("1", "Outer Stage", thread_id):
            with tracker.track_stage("1.1", "Inner Stage", thread_id):
                pass

        summary = tracker.get_execution_summary(thread_id)
        stages = summary["stages"]

        # Only top-level stages are in the main stages list
        assert len(stages) == 1
        assert stages[0]["stage_id"] == "1"
        assert stages[0]["stage_name"] == "Outer Stage"

        # Nested stages should be in substages
        assert "substages" in stages[0]
        assert len(stages[0]["substages"]) == 1
        assert stages[0]["substages"][0]["stage_id"] == "1.1"
        assert stages[0]["substages"][0]["stage_name"] == "Inner Stage"

    def test_exception_in_stage_is_recorded(self, tracker):
        """Test that exceptions within tracked stages are properly recorded."""
        thread_id = "exception-thread"

        with pytest.raises(ValueError):
            with tracker.track_stage("1", "Failing Stage", thread_id):
                raise ValueError("Test exception")

        summary = tracker.get_execution_summary(thread_id)
        stage = summary["stages"][0]

        assert stage["stage_id"] == "1"
        # Check that error information is recorded
        assert stage["success"] is False
        assert "error_message" in stage
        assert "error_type" in stage
        assert stage["error_message"] == "Test exception"
        assert stage["error_type"] == "ValueError"

    def test_sampling_with_special_characters(self, tracker):
        """Test sampling with thread IDs containing special characters."""
        special_thread_ids = [
            "thread-with-dashes-and-numbers-123",
            "thread_with_underscores_456",
            "thread.with.dots.789",
            "thread/with/slashes/012",
            "thread:with:colons:345",
        ]

        for thread_id in special_thread_ids:
            # Should not raise exceptions
            result = tracker.should_track(thread_id)
            assert isinstance(result, bool)

            # Should be deterministic
            result2 = tracker.should_track(thread_id)
            assert result == result2

    def test_empty_thread_id_handling(self, tracker):
        """Test handling of empty or None thread IDs."""
        # Empty string
        result = tracker.should_track("")
        assert isinstance(result, bool)

        # None (should handle gracefully or raise)
        try:
            tracker.should_track(None)
        except (TypeError, AttributeError):
            pass  # Expected for None input

    def test_very_long_thread_id(self, tracker):
        """Test sampling with extremely long thread IDs."""
        long_thread_id = "thread-" + "a" * 1000

        result = tracker.should_track(long_thread_id)
        assert isinstance(result, bool)

        # Should still be deterministic
        result2 = tracker.should_track(long_thread_id)
        assert result == result2

    def test_unicode_thread_id(self, tracker):
        """Test sampling with Unicode characters in thread ID."""
        unicode_thread_ids = ["thread-测试", "thread-café", "thread-🚀", "thread-русский"]

        for thread_id in unicode_thread_ids:
            result = tracker.should_track(thread_id)
            assert isinstance(result, bool)

            # Should be deterministic
            result2 = tracker.should_track(thread_id)
            assert result == result2

    def test_stage_tracking_without_thread_id(self, tracker):
        """Test stage tracking when no thread_id is provided."""
        # Should handle None thread_id gracefully
        try:
            with tracker.track_stage("1", "No Thread Stage", None):
                pass
        except (TypeError, AttributeError):
            pass  # Expected behavior

    def test_get_execution_summary_for_unknown_thread(self, tracker):
        """Test getting summary for thread with no recorded stages."""
        summary = tracker.get_execution_summary("unknown-thread")

        assert isinstance(summary, dict)
        assert "stages" in summary
        assert len(summary["stages"]) == 0

    def test_clear_unknown_thread_data(self, tracker):
        """Test clearing data for thread that doesn't exist."""
        # Should not raise exception
        tracker.clear_thread_data("unknown-thread")

    def test_multiple_stages_same_id_different_threads(self, tracker):
        """Test multiple threads with same stage ID are independent."""
        thread_1 = "thread-a"
        thread_2 = "thread-b"

        with tracker.track_stage("1", "Stage One", thread_1):
            pass
        with tracker.track_stage("1", "Stage One", thread_2):
            pass

        summary_1 = tracker.get_execution_summary(thread_1)
        summary_2 = tracker.get_execution_summary(thread_2)

        assert len(summary_1["stages"]) == 1
        assert len(summary_2["stages"]) == 1
        assert summary_1["stages"][0]["thread_id"] != summary_2["stages"][0]["thread_id"]

    def test_memory_cleanup_on_multiple_operations(self, tracker):
        """Test memory cleanup works with many operations."""
        thread_ids = [f"cleanup-thread-{i}" for i in range(10)]

        # Create data for multiple threads
        for thread_id in thread_ids:
            with tracker.track_stage("1", "Test Stage", thread_id):
                pass

        # Clear all data
        for thread_id in thread_ids:
            tracker.clear_thread_data(thread_id)

        # Verify all data is cleared
        for thread_id in thread_ids:
            summary = tracker.get_execution_summary(thread_id)
            assert len(summary.get("stages", [])) == 0
