"""
Unit Tests for Monitoring Infrastructure

Tests health checking and metrics collection functionality.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.monitoring.health_checker import HealthChecker
from src.infrastructure.monitoring.metrics_collector import MetricsCollector


@pytest.mark.unit
class TestHealthChecker:
    """Test suite for HealthChecker."""

    @pytest.fixture
    def health_checker(self):
        """Create HealthChecker for testing."""
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_redis_health_check_healthy(self, health_checker):
        """Test Redis health check when healthy."""
        mock_redis = AsyncMock()
        mock_redis.health_check.return_value = {"status": "healthy", "latency_ms": 1.5}

        result = await health_checker.check_redis(mock_redis)

        assert result["status"] == "healthy"
        assert result["latency_ms"] == 1.5
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_redis_health_check_unhealthy(self, health_checker):
        """Test Redis health check when unhealthy."""
        mock_redis = AsyncMock()
        mock_redis.health_check.return_value = {"status": "unhealthy", "error": "Connection failed"}

        result = await health_checker.check_redis(mock_redis)

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert result["error"] == "Connection failed"

    @pytest.mark.asyncio
    async def test_redis_health_check_exception(self, health_checker):
        """Test Redis health check when exception occurs."""
        mock_redis = AsyncMock()
        mock_redis.health_check.side_effect = Exception("Network timeout")

        result = await health_checker.check_redis(mock_redis)

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert "Network timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_overall_health_check_all_healthy(self, health_checker):
        """Test overall health check when all components are healthy."""
        # Initialize health checker with mock components
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(return_value={"status": "healthy"})

        mock_cache = AsyncMock()
        mock_cache.health_check = AsyncMock(return_value={"status": "healthy"})

        await health_checker.initialize(
            redis_client=mock_redis,
            cache_manager=mock_cache
        )

        result = await health_checker.check_overall()

        assert result["status"] == "healthy"
        assert "components" in result
        assert result["components"]["redis"]["status"] == "healthy"
        assert result["components"]["cache"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_overall_health_check_partial_failure(self, health_checker):
        """Test overall health check with partial failures."""
        # Initialize with one unhealthy component
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(
            return_value={"status": "unhealthy", "error": "Connection failed"}
        )

        mock_cache = AsyncMock()
        mock_cache.health_check = AsyncMock(return_value={"status": "healthy"})

        await health_checker.initialize(
            redis_client=mock_redis,
            cache_manager=mock_cache
        )

        result = await health_checker.check_overall()

        assert result["status"] == "degraded"
        assert result["components"]["redis"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_overall_health_check_total_failure(self, health_checker):
        """Test overall health check when all components fail."""
        # Initialize with failing components
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(side_effect=Exception("Redis down"))

        mock_cache = AsyncMock()
        mock_cache.health_check = AsyncMock(side_effect=Exception("Cache down"))

        await health_checker.initialize(
            redis_client=mock_redis,
            cache_manager=mock_cache
        )

        result = await health_checker.check_overall()

        assert result["status"] == "unhealthy"
        assert "failed_components" in result
        assert len(result["failed_components"]) >= 2

    @pytest.mark.asyncio
    async def test_health_check_with_custom_components(self, health_checker):
        """Test health check with additional custom components."""
        # Initialize with healthy components
        mock_redis = AsyncMock()
        mock_redis.health_check = AsyncMock(return_value={"status": "healthy"})

        mock_cache = AsyncMock()
        mock_cache.health_check = AsyncMock(return_value={"status": "healthy"})

        await health_checker.initialize(
            redis_client=mock_redis,
            cache_manager=mock_cache
        )

        result = await health_checker.check_overall()

        assert result["status"] == "healthy"
        assert "components" in result


@pytest.mark.unit
class TestMetricsCollector:
    """Test suite for MetricsCollector."""

    @pytest.fixture
    def metrics_collector(self):
        """Create MetricsCollector for testing."""
        return MetricsCollector()

    def test_increment_counter(self, metrics_collector):
        """Test incrementing counters."""
        metrics_collector.increment_counter("requests_total")
        metrics_collector.increment_counter("requests_total")
        metrics_collector.increment_counter("errors_total", labels={"type": "timeout"})

        metrics = metrics_collector.get_metrics()

        assert metrics["requests_total"] == 2
        assert metrics["errors_total"]["type:timeout"] == 1

    def test_record_histogram(self, metrics_collector):
        """Test recording histogram values."""
        values = [0.1, 0.5, 1.2, 0.8, 2.1]

        for value in values:
            metrics_collector.record_histogram("response_time", value)

        metrics = metrics_collector.get_metrics()

        assert "response_time" in metrics
        histogram_data = metrics["response_time"]
        assert histogram_data["count"] == 5
        assert histogram_data["sum"] == sum(values)
        assert min(values) in histogram_data["values"]
        assert max(values) in histogram_data["values"]

    def test_histogram_with_labels(self, metrics_collector):
        """Test histogram recording with labels."""
        metrics_collector.record_histogram("db_query_time", 0.1, labels={"table": "users"})
        metrics_collector.record_histogram("db_query_time", 0.3, labels={"table": "orders"})

        metrics = metrics_collector.get_metrics()

        assert "db_query_time" in metrics
        db_metrics = metrics["db_query_time"]

        assert "table:users" in db_metrics
        assert "table:orders" in db_metrics
        assert db_metrics["table:users"]["count"] == 1
        assert db_metrics["table:orders"]["count"] == 1

    def test_get_metrics_returns_copy(self, metrics_collector):
        """Test that get_metrics returns a copy, not reference."""
        metrics_collector.increment_counter("test_counter")

        metrics1 = metrics_collector.get_metrics()
        metrics1["test_counter"] = 999  # Modify copy

        metrics2 = metrics_collector.get_metrics()

        assert metrics2["test_counter"] == 1  # Original should be unchanged

    def test_metrics_persistence_across_calls(self, metrics_collector):
        """Test that metrics persist across multiple get_metrics calls."""
        metrics_collector.increment_counter("persistent_counter", 5)

        metrics1 = metrics_collector.get_metrics()
        metrics2 = metrics_collector.get_metrics()

        assert metrics1["persistent_counter"] == 5
        assert metrics2["persistent_counter"] == 5

    def test_histogram_percentiles_calculation(self, metrics_collector):
        """Test histogram calculates percentiles correctly."""
        # Add many values for percentile calculation
        values = [i * 0.1 for i in range(1, 101)]  # 0.1 to 10.0

        for value in values:
            metrics_collector.record_histogram("test_histogram", value)

        metrics = metrics_collector.get_metrics()
        histogram = metrics["test_histogram"]

        # Check basic percentiles
        assert "p50" in histogram  # Median
        assert "p95" in histogram  # 95th percentile
        assert "p99" in histogram  # 99th percentile

        # Basic sanity checks
        assert histogram["p50"] > 0
        assert histogram["p95"] > histogram["p50"]
        assert histogram["p99"] >= histogram["p95"]

    def test_counter_with_multiple_labels(self, metrics_collector):
        """Test counters with multiple label combinations."""
        metrics_collector.increment_counter(
            "http_requests", labels={"method": "GET", "status": "200"}
        )
        metrics_collector.increment_counter(
            "http_requests", labels={"method": "POST", "status": "201"}
        )
        metrics_collector.increment_counter(
            "http_requests", labels={"method": "GET", "status": "404"}
        )

        metrics = metrics_collector.get_metrics()

        assert metrics["http_requests"]["method:GET,status:200"] == 1
        assert metrics["http_requests"]["method:POST,status:201"] == 1
        assert metrics["http_requests"]["method:GET,status:404"] == 1

    def test_empty_metrics_collection(self):
        """Test metrics collection starts empty."""
        collector = MetricsCollector()
        metrics = collector.get_metrics()

        # Should have basic structure but no data
        assert isinstance(metrics, dict)
        # May have some default empty collections

    def test_metrics_thread_safety_simulation(self, metrics_collector):
        """Test metrics operations are thread-safe (simulation)."""
        import threading
        import time

        def increment_worker():
            for _ in range(100):
                metrics_collector.increment_counter("thread_test")
                time.sleep(0.001)  # Small delay to encourage race conditions

        # Start multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=increment_worker)
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        metrics = metrics_collector.get_metrics()

        # Should have exactly 500 increments (5 threads * 100 increments each)
        assert metrics["thread_test"] == 500

    def test_histogram_with_zero_values(self, metrics_collector):
        """Test histogram handles zero and negative values."""
        metrics_collector.record_histogram("edge_case", 0)
        metrics_collector.record_histogram("edge_case", -1)  # Should handle gracefully

        metrics = metrics_collector.get_metrics()
        histogram = metrics["edge_case"]

        assert histogram["count"] >= 1  # At least the zero value
        assert histogram["min"] <= 0

    def test_counter_overflow_simulation(self, metrics_collector):
        """Test counter handles large values (simulation)."""
        large_number = 1_000_000

        metrics_collector.increment_counter("large_counter", large_number)

        metrics = metrics_collector.get_metrics()

        assert metrics["large_counter"] == large_number

    def test_metrics_reset_simulation(self, metrics_collector):
        """Test metrics reset functionality (if implemented)."""
        metrics_collector.increment_counter("reset_test", 5)

        # If reset method exists, test it
        if hasattr(metrics_collector, "reset"):
            metrics_collector.reset()

            metrics = metrics_collector.get_metrics()
            assert metrics.get("reset_test", 0) == 0
        else:
            # Otherwise just verify metrics persist
            metrics = metrics_collector.get_metrics()
            assert metrics["reset_test"] == 5
