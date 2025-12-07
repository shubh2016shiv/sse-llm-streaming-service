#!/usr/bin/env python3
"""
Metrics Collector with Prometheus Integration

This module provides production-ready metrics collection with:
- Prometheus-compatible metrics
- Request latency histograms by stage
- Throughput counters
- Error rates by type
- Cache hit/miss rates
- Circuit breaker states
- Connection counts

Architectural Decision: prometheus-client for industry-standard metrics
- Compatible with Grafana dashboards
- Efficient storage and aggregation
- Histogram buckets for latency percentiles

Author: Senior Solution Architect
Date: 2025-12-05
"""


from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Metric Definitions
# ============================================================================

# Request metrics
REQUEST_COUNT = Counter(
    'sse_requests_total',
    'Total number of SSE stream requests',
    ['status', 'provider', 'model']
)

REQUEST_DURATION = Histogram(
    'sse_request_duration_seconds',
    'Request duration in seconds',
    ['stage'],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

STAGE_DURATION = Histogram(
    'sse_stage_duration_seconds',
    'Stage execution duration in seconds',
    ['stage', 'substage'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# Connection metrics
ACTIVE_CONNECTIONS = Gauge(
    'sse_active_connections',
    'Number of active SSE connections'
)

# Cache metrics
CACHE_HITS = Counter(
    'sse_cache_hits_total',
    'Total cache hits',
    ['tier']  # L1 or L2
)

CACHE_MISSES = Counter(
    'sse_cache_misses_total',
    'Total cache misses',
    ['tier']
)

# Circuit breaker metrics
CIRCUIT_BREAKER_STATE = Gauge(
    'sse_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=half_open, 2=open)',
    ['provider']
)

CIRCUIT_BREAKER_FAILURES = Counter(
    'sse_circuit_breaker_failures_total',
    'Total circuit breaker recorded failures',
    ['provider']
)

# Rate limiting metrics
RATE_LIMIT_EXCEEDED = Counter(
    'sse_rate_limit_exceeded_total',
    'Total rate limit exceeded events',
    ['user_type']  # ip, user, token
)

# Error metrics
ERRORS = Counter(
    'sse_errors_total',
    'Total errors by type',
    ['error_type', 'stage']
)

# Provider metrics
PROVIDER_REQUESTS = Counter(
    'sse_provider_requests_total',
    'Total requests to LLM providers',
    ['provider', 'status']  # success, failure, timeout
)

PROVIDER_LATENCY = Histogram(
    'sse_provider_latency_seconds',
    'Provider response latency',
    ['provider'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

# Streaming metrics
CHUNKS_STREAMED = Counter(
    'sse_chunks_streamed_total',
    'Total chunks streamed',
    ['provider']
)

STREAM_DURATION = Histogram(
    'sse_stream_duration_seconds',
    'Total stream duration',
    ['provider'],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
)

# Queue metrics
QUEUE_PRODUCE_ATTEMPTS = Counter(
    'sse_queue_produce_attempts_total',
    'Total queue produce attempts',
    ['queue_type']
)

QUEUE_PRODUCE_SUCCESS = Counter(
    'sse_queue_produce_success_total',
    'Total successful queue produces',
    ['queue_type']
)

QUEUE_PRODUCE_FAILURES = Counter(
    'sse_queue_produce_failures_total',
    'Total failed queue produces',
    ['queue_type', 'reason']
)

QUEUE_DEPTH = Gauge(
    'sse_queue_depth',
    'Current queue depth',
    ['queue_name']
)

QUEUE_BACKPRESSURE_RETRIES = Counter(
    'sse_queue_backpressure_retries_total',
    'Total backpressure retry attempts',
    ['queue_type']
)

# App info
APP_INFO = Info(
    'sse_app',
    'Application information'
)


class MetricsCollector:
    """
    Centralized metrics collector.

    STAGE-M: Metrics collection

    This class provides:
    - Convenient methods for recording metrics
    - Integration with execution tracker
    - Prometheus metrics export

    Usage:
        metrics = MetricsCollector()

        # Record request
        metrics.record_request("success", "openai", "gpt-4")

        # Record stage duration
        metrics.record_stage_duration("2.1", "L1_lookup", 0.005)

        # Get Prometheus output
        output = metrics.get_prometheus_metrics()
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.settings = get_settings()

        # Set app info
        APP_INFO.info({
            'version': self.settings.app.APP_VERSION,
            'environment': self.settings.app.ENVIRONMENT,
            'app_name': self.settings.app.APP_NAME
        })

        logger.info("Metrics collector initialized", stage="M.0")

    # =========================================================================
    # Request Metrics
    # =========================================================================

    def record_request(
        self,
        status: str,
        provider: str = "unknown",
        model: str = "unknown"
    ) -> None:
        """Record a request."""
        REQUEST_COUNT.labels(status=status, provider=provider, model=model).inc()

    def record_request_duration(self, stage: str, duration_seconds: float) -> None:
        """Record request duration by stage."""
        REQUEST_DURATION.labels(stage=stage).observe(duration_seconds)

    # =========================================================================
    # Stage Metrics
    # =========================================================================

    def record_stage_duration(
        self,
        stage: str,
        substage: str,
        duration_seconds: float
    ) -> None:
        """Record stage execution duration."""
        STAGE_DURATION.labels(stage=stage, substage=substage).observe(duration_seconds)

    # =========================================================================
    # Connection Metrics
    # =========================================================================

    def set_active_connections(self, count: int) -> None:
        """Set active connection count."""
        ACTIVE_CONNECTIONS.set(count)

    def increment_connections(self) -> None:
        """Increment active connections."""
        ACTIVE_CONNECTIONS.inc()

    def decrement_connections(self) -> None:
        """Decrement active connections."""
        ACTIVE_CONNECTIONS.dec()

    # =========================================================================
    # Cache Metrics
    # =========================================================================

    def record_cache_hit(self, tier: str) -> None:
        """Record cache hit."""
        CACHE_HITS.labels(tier=tier).inc()

    def record_cache_miss(self, tier: str) -> None:
        """Record cache miss."""
        CACHE_MISSES.labels(tier=tier).inc()

    # =========================================================================
    # Circuit Breaker Metrics
    # =========================================================================

    def set_circuit_state(self, provider: str, state: str) -> None:
        """Set circuit breaker state."""
        state_value = {"closed": 0, "half_open": 1, "open": 2}.get(state, 0)
        CIRCUIT_BREAKER_STATE.labels(provider=provider).set(state_value)

    def record_circuit_failure(self, provider: str) -> None:
        """Record circuit breaker failure."""
        CIRCUIT_BREAKER_FAILURES.labels(provider=provider).inc()

    # =========================================================================
    # Rate Limiting Metrics
    # =========================================================================

    def record_rate_limit_exceeded(self, user_type: str) -> None:
        """Record rate limit exceeded event."""
        RATE_LIMIT_EXCEEDED.labels(user_type=user_type).inc()

    # =========================================================================
    # Error Metrics
    # =========================================================================

    def record_error(self, error_type: str, stage: str) -> None:
        """Record error."""
        ERRORS.labels(error_type=error_type, stage=stage).inc()

    # =========================================================================
    # Provider Metrics
    # =========================================================================

    def record_provider_request(self, provider: str, status: str) -> None:
        """Record provider request."""
        PROVIDER_REQUESTS.labels(provider=provider, status=status).inc()

    def record_provider_latency(self, provider: str, duration_seconds: float) -> None:
        """Record provider latency."""
        PROVIDER_LATENCY.labels(provider=provider).observe(duration_seconds)

    # =========================================================================
    # Streaming Metrics
    # =========================================================================

    def record_chunks_streamed(self, provider: str, count: int = 1) -> None:
        """Record chunks streamed."""
        CHUNKS_STREAMED.labels(provider=provider).inc(count)

    def record_stream_duration(self, provider: str, duration_seconds: float) -> None:
        """Record stream duration."""
        STREAM_DURATION.labels(provider=provider).observe(duration_seconds)

    # =========================================================================
    # Queue Metrics
    # =========================================================================

    def record_queue_produce_attempt(self, queue_type: str) -> None:
        """Record queue produce attempt."""
        QUEUE_PRODUCE_ATTEMPTS.labels(queue_type=queue_type).inc()

    def record_queue_produce_success(self, queue_type: str) -> None:
        """Record successful queue produce."""
        QUEUE_PRODUCE_SUCCESS.labels(queue_type=queue_type).inc()

    def record_queue_produce_failure(self, queue_type: str, reason: str) -> None:
        """Record failed queue produce."""
        QUEUE_PRODUCE_FAILURES.labels(queue_type=queue_type, reason=reason).inc()

    def record_queue_depth(self, queue_name: str, depth: int) -> None:
        """Record current queue depth."""
        QUEUE_DEPTH.labels(queue_name=queue_name).set(depth)

    def record_queue_backpressure_retry(self, queue_type: str) -> None:
        """Record backpressure retry attempt."""
        QUEUE_BACKPRESSURE_RETRIES.labels(queue_type=queue_type).inc()

    # =========================================================================
    # Export
    # =========================================================================

    def get_prometheus_metrics(self) -> bytes:
        """
        Get Prometheus metrics output.

        Returns:
            bytes: Prometheus text format metrics
        """
        return generate_latest(REGISTRY)

    def get_content_type(self) -> str:
        """Get Prometheus content type."""
        return CONTENT_TYPE_LATEST


# Global metrics collector
_metrics: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
