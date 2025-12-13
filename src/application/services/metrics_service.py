"""
Metrics Service - Educational Documentation
============================================

WHAT IS THIS SERVICE?
---------------------
MetricsService handles the complex business logic of aggregating metrics from Prometheus
for the performance dashboard. This extracts 210+ lines of query logic from the route
handler into a dedicated, testable service.

WHY EXTRACT THIS LOGIC?
------------------------
BEFORE (in route):
- 210 lines of PromQL queries and aggregations
- Mixed concerns (HTTP + business logic)
- Difficult to test (requires HTTP mocking)
- Cognitive overload (too much to understand at once)

AFTER (in service):
- Route handles HTTP (20 lines)
- Service handles business logic (isolated, testable)
- Each method focused on one concern
- Easy to test with mocked Prometheus client

GOOGLE-LEVEL PATTERNS:
-----------------------
1. **Dependency Injection**: Service receives dependencies (doesn't create them)
2. **Caching**: Expensive operations cached with TTL
3. **Error Handling**: Graceful degradation when Prometheus unavailable
4. **Separation of Concerns**: Each method does one thing well
5. **Type Safety**: Full type hints for IDE support and runtime validation
"""

from datetime import datetime, timedelta
from typing import Any

import structlog

from src.application.api.models.admin import (
    CacheMetrics,
    ConnectionMetrics,
    ConnectionPoolState,
    LatencyMetrics,
    ProcessingStage,
    PrometheusStatsResponse,
    QueueMetrics,
    ThroughputMetrics,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# METRICS CACHE: Performance Optimization
# ============================================================================
# Why cache metrics?
# - Prometheus queries can be expensive (scans time-series data)
# - Dashboard polls every few seconds (doesn't need real-time microsecond accuracy)
# - Cache for 30 seconds = 30x fewer Prometheus queries
# - Reduces load on Prometheus, improves dashboard response time


class MetricsCache:
    """
    Simple TTL cache for expensive metrics operations.

    DESIGN DECISIONS:
    -----------------
    - In-memory cache (not Redis): Metrics are instance-specific, no need to share
    - TTL-based expiration: Stale data after 30 seconds is fine for dashboard
    - No LRU eviction: Cache is small (few keys), no memory pressure

    PRODUCTION CONSIDERATIONS:
    --------------------------
    For high-traffic production, consider:
    - Distributed cache (Redis) to share across instances
    - Prometheus recording rules (pre-computed aggregations)
    - Adaptive TTL based on load
    """

    def __init__(self, ttl_seconds: int = 30):
        """
        Initialize metrics cache.

        Args:
            ttl_seconds: Time-to-live for cached values (default: 30 seconds)
        """
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        logger.info(
            "metrics_cache_initialized",
            ttl_seconds=ttl_seconds,
            rationale="Reduce Prometheus query load and improve dashboard response time",
        )

    async def get_or_compute(self, key: str, compute_fn):
        """
        Get cached value or compute and cache it.

        CACHING STRATEGY:
        -----------------
        1. Check if key exists in cache
        2. Check if cached value is still fresh (within TTL)
        3. If fresh, return cached value
        4. If stale or missing, call compute_fn to get fresh value
        5. Store in cache with current timestamp

        Args:
            key: Cache key (e.g., "prometheus_stats")
            compute_fn: Async function to compute value if cache miss

        Returns:
            Cached or freshly computed value
        """
        # Cache hit: Value exists and is fresh
        if key in self._cache:
            value, timestamp = self._cache[key]
            age = datetime.now() - timestamp

            if age < self._ttl:
                logger.debug(
                    "metrics_cache_hit",
                    key=key,
                    age_seconds=age.total_seconds(),
                    ttl_seconds=self._ttl.total_seconds(),
                )
                return value
            else:
                logger.debug(
                    "metrics_cache_expired",
                    key=key,
                    age_seconds=age.total_seconds(),
                    ttl_seconds=self._ttl.total_seconds(),
                )

        # Cache miss: Compute fresh value
        logger.debug("metrics_cache_miss", key=key)
        value = await compute_fn()
        self._cache[key] = (value, datetime.now())

        return value


# ============================================================================
# METRICS SERVICE: Business Logic Layer
# ============================================================================


class MetricsService:
    """
    Service for aggregating Prometheus metrics.

    RESPONSIBILITIES:
    -----------------
    1. Query Prometheus for metrics across all application instances
    2. Aggregate and transform data for dashboard consumption
    3. Handle Prometheus unavailability gracefully
    4. Cache expensive operations

    DESIGN PRINCIPLES:
    ------------------
    - Stateless: No instance variables for request-specific data
    - Dependency injection: Receives Prometheus client, doesn't create it
    - Error resilience: Returns partial data if some queries fail
    - Observability: Logs all operations with structured logging
    """

    def __init__(self, prometheus_client, settings):
        """
        Initialize metrics service.

        Args:
            prometheus_client: Client for querying Prometheus
            settings: Application settings (for connection limits, etc.)
        """
        self.client = prometheus_client
        self.settings = settings
        self._cache = MetricsCache(ttl_seconds=30)

        logger.info(
            "metrics_service_initialized",
            cache_ttl_seconds=30,
            context="Service will cache metrics for 30 seconds to reduce Prometheus load",
        )

    async def _safe_query(self, promql: str) -> float | None:
        """
        Query Prometheus and extract scalar value, handling errors gracefully.

        DEFENSIVE PROGRAMMING:
        ----------------------
        - Catches all exceptions (don't crash on Prometheus errors)
        - Handles NaN and Inf (not JSON-serializable)
        - Returns None on any error (callers handle None appropriately)

        PROMETHEUS QUERIES:
        -------------------
        PromQL is Prometheus' query language. Examples:
        - rate(metric[5m]): Per-second rate over 5-minute window
        - histogram_quantile(0.99, ...): 99th percentile latency
        - sum(metric): Aggregate across all instances

        Args:
            promql: Prometheus query language string

        Returns:
            Scalar float value or None if query failed
        """
        try:
            response = await self.client.query(promql)
            value = self.client.extract_scalar_value(response)

            # NaN and Inf are not JSON-serializable, treat as None
            if value is not None and (
                value != value  # NaN check (NaN != NaN)
                or value == float("inf")
                or value == float("-inf")
            ):
                logger.warning(
                    "prometheus_query_returned_invalid_value",
                    promql=promql,
                    value=str(value),
                    action="Treating as None",
                )
                return None

            return value

        except Exception as e:
            logger.error(
                "prometheus_query_failed",
                promql=promql,
                error=str(e),
                action="Returning None for this metric",
            )
            return None

    async def _safe_vector_query(self, promql: str) -> dict[str, float]:
        """
        Query Prometheus and extract vector values, handling errors gracefully.

        VECTOR QUERIES:
        ---------------
        Vector queries return multiple labeled values.
        Example: circuit_breaker_state{provider="openai"}
        Returns: {"openai": 0.0, "anthropic": 0.0, ...}

        Args:
            promql: Prometheus query language string

        Returns:
            Dict mapping labels to values, or empty dict on error
        """
        try:
            response = await self.client.query(promql)
            values = self.client.extract_vector_values(response)

            # Filter out NaN and Inf values
            filtered = {
                k: v
                for k, v in values.items()
                if v == v and v != float("inf") and v != float("-inf")
            }

            return filtered

        except Exception as e:
            logger.error(
                "prometheus_vector_query_failed",
                promql=promql,
                error=str(e),
                action="Returning empty dict",
            )
            return {}

    async def _get_latency_percentiles(
        self, stage: str, percentiles: list[float]
    ) -> dict[str, float]:
        """
        Get latency percentiles for a specific stage.

        HELPER METHOD PATTERN:
        ----------------------
        This eliminates code duplication. Before, the same histogram_quantile
        query was repeated for p50, p90, p99. Now it's one loop.

        HISTOGRAM_QUANTILE EXPLAINED:
        -----------------------------
        Prometheus histograms store latency distributions in buckets.
        histogram_quantile() calculates percentiles from these buckets.

        Example: histogram_quantile(0.99, metric) = 99th percentile latency

        Args:
            stage: Processing stage ID (e.g., "1" for cache lookup)
            percentiles: List of percentiles (e.g., [0.5, 0.9, 0.99])

        Returns:
            Dict mapping percentile keys (e.g., "p50") to latency values
        """
        results = {}

        for p in percentiles:
            # Build PromQL query for this percentile
            query = (
                f"histogram_quantile({p}, "
                f'sum by (le) (rate(sse_stage_duration_seconds_bucket{{stage="{stage}"}}[5m])))'
            )

            value = await self._safe_query(query)

            # Convert percentile 0.99 to key "p99"
            percentile_key = f"p{int(p * 100)}"
            results[percentile_key] = value if value is not None else 0.0

        return results

    async def get_latency_metrics(self) -> LatencyMetrics:
        """
        Get latency metrics for all processing stages.

        METRICS COLLECTED:
        ------------------
        - Per-stage latency percentiles (p50, p90, p99)
        - Overall end-to-end P99 latency

        PERFORMANCE INSIGHTS:
        ---------------------
        By comparing stage latencies, you can identify bottlenecks:
        - High stage 1 latency: Cache is slow
        - High stage 3 latency: LLM provider is slow
        - High stage 4 latency: Network/streaming issues

        Returns:
            LatencyMetrics with per-stage and overall latencies
        """
        logger.debug("get_latency_metrics_started")

        # Get all processing stages
        stages = [stage.value for stage in ProcessingStage]
        stage_latency: dict[str, dict[str, float]] = {}

        # Query latency for each stage
        for stage in stages:
            percentiles = await self._get_latency_percentiles(
                stage=stage, percentiles=[0.50, 0.90, 0.99]
            )

            if percentiles and any(v > 0 for v in percentiles.values()):
                stage_latency[stage] = percentiles

        # Query overall P99 latency (end-to-end)
        overall_p99_query = (
            "histogram_quantile(0.99, sum by (le) (rate(sse_request_duration_seconds_bucket[5m])))"
        )
        overall_p99 = await self._safe_query(overall_p99_query)
        overall_p99_ms = (overall_p99 * 1000) if overall_p99 is not None else 0.0

        logger.debug(
            "get_latency_metrics_completed",
            stages_with_data=len(stage_latency),
            overall_p99_ms=overall_p99_ms,
        )

        return LatencyMetrics(stages=stage_latency, overall_p99_ms=overall_p99_ms)

    async def get_connection_metrics(self) -> ConnectionMetrics:
        """
        Get connection pool metrics.

        CONNECTION POOL PATTERN:
        ------------------------
        Connection pools reuse connections to avoid overhead.

        Metrics:
        - active: Currently in-use connections
        - limit: Maximum allowed connections
        - utilization: active / limit * 100
        - state: healthy/degraded/exhausted

        Returns:
            ConnectionMetrics with pool statistics
        """
        logger.debug("get_connection_metrics_started")

        # Query active connections (sum across all instances)
        active_query = "sum(sse_active_connections)"
        active = await self._safe_query(active_query) or 0.0
        active_int = int(active)

        # Get limit from settings
        limit = getattr(self.settings, "MAX_CONCURRENT_CONNECTIONS", 90)

        # Calculate utilization
        utilization = (active / limit * 100) if limit > 0 else 0.0

        # Determine state based on utilization
        if utilization < 80:
            state = ConnectionPoolState.HEALTHY
        elif utilization < 95:
            state = ConnectionPoolState.DEGRADED
        else:
            state = ConnectionPoolState.EXHAUSTED

        logger.debug(
            "get_connection_metrics_completed",
            active=active_int,
            limit=limit,
            utilization_percent=utilization,
            state=state.value,
        )

        return ConnectionMetrics(
            active=active_int, limit=limit, utilization_percent=round(utilization, 2), state=state
        )

    async def get_throughput_metrics(self) -> ThroughputMetrics:
        """
        Get request throughput and error rate metrics.

        RATE CALCULATION:
        -----------------
        rate(metric[5m]) calculates per-second rate over 5-minute window.
        This smooths out spikes and gives stable throughput measurement.

        ERROR BUDGET:
        -------------
        Error rate % helps track SLO compliance.
        Example: 99.9% uptime = 0.1% error budget

        Returns:
            ThroughputMetrics with requests/sec and error rate
        """
        logger.debug("get_throughput_metrics_started")

        # Query request throughput
        throughput_query = "sum(rate(sse_requests_total[5m]))"
        requests_per_sec = await self._safe_query(throughput_query) or 0.0

        # Query error rate
        error_rate_query = "sum(rate(sse_errors_total[5m]))"
        error_rate = await self._safe_query(error_rate_query) or 0.0

        # Calculate error rate percentage
        error_rate_percent = (error_rate / requests_per_sec * 100) if requests_per_sec > 0 else 0.0

        logger.debug(
            "get_throughput_metrics_completed",
            requests_per_sec=requests_per_sec,
            error_rate_percent=error_rate_percent,
        )

        return ThroughputMetrics(
            requests_per_sec=round(requests_per_sec, 2),
            error_rate_percent=round(error_rate_percent, 2),
        )

    async def get_cache_metrics(self) -> CacheMetrics:
        """
        Get cache performance metrics.

        TWO-TIER CACHE:
        ---------------
        L1: In-memory LRU (fast, limited capacity)
        L2: Redis (slower, larger capacity, shared)

        HIT RATE IMPORTANCE:
        --------------------
        Cache hit = ~1ms response
        Cache miss + LLM = ~1000ms response
        80% hit rate = 80% of requests are 1000x faster!

        Returns:
            CacheMetrics with hit rates and throughput
        """
        logger.debug("get_cache_metrics_started")

        # Query cache hits and misses
        hits_query = "sum(rate(sse_cache_hits_total[5m]))"
        misses_query = "sum(rate(sse_cache_misses_total[5m]))"

        hits = await self._safe_query(hits_query) or 0.0
        misses = await self._safe_query(misses_query) or 0.0

        # Calculate hit rate
        total_requests = hits + misses
        hit_rate_percent = (hits / total_requests * 100) if total_requests > 0 else 0.0

        # Query L1 and L2 hits separately
        l1_hits_query = 'sum(rate(sse_cache_hits_total{tier="L1"}[5m]))'
        l2_hits_query = 'sum(rate(sse_cache_hits_total{tier="L2"}[5m]))'

        l1_hits = await self._safe_query(l1_hits_query) or 0.0
        l2_hits = await self._safe_query(l2_hits_query) or 0.0

        logger.debug(
            "get_cache_metrics_completed",
            hit_rate_percent=hit_rate_percent,
            l1_hits_per_sec=l1_hits,
            l2_hits_per_sec=l2_hits,
        )

        return CacheMetrics(
            hit_rate_percent=round(hit_rate_percent, 2),
            l1_hits_per_sec=round(l1_hits, 2),
            l2_hits_per_sec=round(l2_hits, 2),
        )

    async def get_queue_metrics(self) -> QueueMetrics:
        """
        Get message queue metrics for failover monitoring.

        QUEUE FAILOVER:
        ---------------
        When connection pool exhausted, requests go to queue.
        Workers drain queue when capacity available.

        MONITORING:
        -----------
        - depth > 0: System under load
        - depth increasing: Need more workers
        - produce_failures > 0: Queue system issues

        Returns:
            QueueMetrics with depth and failure rate
        """
        logger.debug("get_queue_metrics_started")

        # Query queue depth
        depth_query = "sum(sse_queue_depth) or vector(0)"
        depth = await self._safe_query(depth_query) or 0.0

        # Query produce failures
        failures_query = "sum(rate(sse_queue_produce_failures_total[5m]))"
        failures = await self._safe_query(failures_query) or 0.0

        logger.debug(
            "get_queue_metrics_completed", depth=int(depth), produce_failures_per_sec=failures
        )

        return QueueMetrics(depth=int(depth), produce_failures_per_sec=round(failures, 2))

    async def get_circuit_breaker_states(self) -> dict[str, str]:
        """
        Get circuit breaker states for all providers.

        STATE MAPPING:
        --------------
        Prometheus stores state as number: 0=closed, 1=half_open, 2=open
        We convert to strings for API consistency.

        Returns:
            Dict mapping provider name to state string
        """
        logger.debug("get_circuit_breaker_states_started")

        query = "sse_circuit_breaker_state"
        states = await self._safe_vector_query(query)

        # Map numeric states to strings
        result = {}
        for provider, state_value in states.items():
            if state_value == 0:
                result[provider] = "closed"
            elif state_value == 1:
                result[provider] = "half_open"
            elif state_value == 2:
                result[provider] = "open"
            else:
                result[provider] = "unknown"

        logger.debug("get_circuit_breaker_states_completed", provider_count=len(result))

        return result

    async def get_aggregated_metrics(self) -> PrometheusStatsResponse:
        """
        Aggregate all Prometheus metrics (cached for 30 seconds).

        CACHING STRATEGY:
        -----------------
        This method is called by the dashboard every few seconds.
        Caching prevents hammering Prometheus with queries.

        GRACEFUL DEGRADATION:
        ---------------------
        If individual metric queries fail, others still succeed.
        Dashboard gets partial data rather than complete failure.

        Returns:
            PrometheusStatsResponse with all aggregated metrics
        """
        return await self._cache.get_or_compute("prometheus_stats", self._compute_all_metrics)

    async def _compute_all_metrics(self) -> PrometheusStatsResponse:
        """
        Internal method to compute all metrics (called on cache miss).

        PARALLEL EXECUTION:
        -------------------
        In production, consider using asyncio.gather() to execute
        all queries in parallel for faster aggregation.
        Trade-off: More load on Prometheus vs faster response.
        """
        logger.info("computing_all_prometheus_metrics")

        # Check if Prometheus is available using the public interface
        # The is_available() method encapsulates circuit breaker state logic
        prometheus_available = self.client.is_available()

        # Get all metrics (each method handles its own errors)
        latency = await self.get_latency_metrics()
        connections = await self.get_connection_metrics()
        throughput = await self.get_throughput_metrics()
        cache = await self.get_cache_metrics()
        queue = await self.get_queue_metrics()
        circuit_breakers = await self.get_circuit_breaker_states()

        logger.info(
            "computed_all_prometheus_metrics",
            prometheus_available=prometheus_available,
            stages_with_latency=len(latency.stages),
            active_connections=connections.active,
            cache_hit_rate=cache.hit_rate_percent,
        )

        return PrometheusStatsResponse(
            prometheus_available=prometheus_available,
            latency=latency,
            connections=connections,
            throughput=throughput,
            cache=cache,
            queue=queue,
            circuit_breakers=circuit_breakers,
        )


# ============================================================================
# DEPENDENCY INJECTION: Singleton Pattern
# ============================================================================
# Why singleton?
# - MetricsService is stateless (safe to share)
# - Prometheus client is expensive to create (connection pooling)
# - Cache should be shared across all requests (more effective)

_metrics_service: MetricsService | None = None


def get_metrics_service() -> MetricsService:
    """
    Get or create the singleton MetricsService instance.

    DEPENDENCY INJECTION PATTERN:
    -----------------------------
    Routes call this function to get the service.
    Benefits:
    - Easy to swap implementation for testing (set _metrics_service to mock)
    - Centralized initialization logic
    - Lazy initialization (created only when needed)

    Returns:
        Singleton MetricsService instance
    """
    global _metrics_service

    if _metrics_service is None:
        # Lazy import to avoid circular dependencies
        from src.core.config.settings import get_settings
        from src.infrastructure.monitoring.prometheus_client import get_prometheus_client

        client = get_prometheus_client()
        settings = get_settings()

        _metrics_service = MetricsService(prometheus_client=client, settings=settings)

        logger.info(
            "metrics_service_singleton_created", context="Service will be reused for all requests"
        )

    return _metrics_service
