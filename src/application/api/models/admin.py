"""
Admin API Response Models - Educational Documentation
======================================================

WHAT ARE RESPONSE MODELS?
-------------------------
Response models are Pydantic classes that define the structure of API responses.
They provide:

1. **Type Safety**: Ensures responses match expected structure at runtime
2. **Validation**: Automatically validates outgoing data
3. **Documentation**: Auto-generates OpenAPI/Swagger documentation
4. **IDE Support**: Enables autocomplete and type checking
5. **Contract Enforcement**: Prevents breaking changes to API responses

PYDANTIC BENEFITS:
------------------
- Runtime validation: Catches bugs before they reach clients
- Serialization: Automatically converts Python objects to JSON
- Deserialization: Parses JSON into typed Python objects
- Documentation: Generates JSON Schema for API docs

GOOGLE-LEVEL BEST PRACTICES:
----------------------------
1. **Explicit Field Descriptions**: Every field has clear documentation
2. **Bounded Values**: Use constraints (ge=0, le=100) to enforce invariants
3. **Immutable by Default**: Use frozen=True when appropriate
4. **Composition Over Inheritance**: Small, focused models that compose together
5. **Forward Compatibility**: Optional fields with defaults for API evolution

This module contains all response models for admin endpoints.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# ENUMS: Type-Safe Constants
# ============================================================================
# Benefits of enums over magic strings:
# 1. Type checking catches typos at development time
# 2. IDE autocomplete shows valid values
# 3. Refactoring is safer (rename enum, not search-replace strings)
# 4. Self-documenting (enum name explains meaning of values)


class ProcessingStage(str, Enum):
    """
    Processing stages for request execution tracking.

    ARCHITECTURE CONTEXT:
    ---------------------
    Every SSE streaming request flows through these stages:

    1. Cache Lookup: Check if response is cached (L1 → L2)
    2. Provider Selection: Choose LLM provider (OpenAI, Anthropic, etc.)
    2.1. Provider Routing: Route request based on model availability
    2.2. Provider Fallback: Fallback if primary provider fails
    3. LLM Call: Execute the actual LLM API call
    4. Response Streaming: Stream chunks back to client via SSE
    5. Cache Update: Store response in cache for future requests
    6. Cleanup: Release resources (connections, memory, etc.)

    WHY str + Enum?
    ---------------
    Inheriting from both str and Enum allows:
    - Serialization to JSON as strings (not integers)
    - Comparison with plain strings: ProcessingStage.CACHE_LOOKUP == "1"
    - Type safety in code while maintaining API backward compatibility
    """

    CACHE_LOOKUP = "1"
    PROVIDER_SELECTION = "2"
    PROVIDER_ROUTING = "2.1"
    PROVIDER_FALLBACK = "2.2"
    LLM_CALL = "3"
    RESPONSE_STREAMING = "4"
    CACHE_UPDATE = "5"
    CLEANUP = "6"


class CircuitBreakerState(str, Enum):
    """
    Circuit breaker states for resilience pattern.

    CIRCUIT BREAKER PATTERN:
    ------------------------
    Prevents cascading failures by tracking external service health.

    States:
    - CLOSED: Normal operation, requests flow through
    - OPEN: Too many failures, requests blocked (fail fast)
    - HALF_OPEN: Testing if service recovered (limited requests)
    - UNKNOWN: State cannot be determined (typically during initialization)

    State Transitions:
    CLOSED → OPEN: When failure threshold exceeded
    OPEN → HALF_OPEN: After timeout period
    HALF_OPEN → CLOSED: If test requests succeed
    HALF_OPEN → OPEN: If test requests fail

    GOOGLE SRE PRINCIPLES:
    ----------------------
    Circuit breakers implement "fail fast" to prevent:
    - Thread pool exhaustion (waiting for slow/dead services)
    - Cascading failures (one service down takes others with it)
    - User-facing timeouts (better to return cached/degraded response)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    UNKNOWN = "unknown"


class ConnectionPoolState(str, Enum):
    """
    Connection pool health states.

    HEALTHY: Pool operating within normal parameters (< 80% utilization)
    DEGRADED: Pool under pressure (80-95% utilization), may need scaling
    EXHAUSTED: Pool at capacity (> 95% utilization), requests will queue/fail
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    EXHAUSTED = "exhausted"


# ============================================================================
# NESTED MODELS: Composable Response Components
# ============================================================================
# Philosophy: Small, focused models that compose into larger responses
# Benefits:
# 1. Reusability across multiple endpoints
# 2. Easier testing (test small components independently)
# 3. Better OpenAPI documentation (nested schemas)
# 4. Flexibility in API evolution (add fields to nested models)


class StageStatistics(BaseModel):
    """
    Performance statistics for a single processing stage.

    PERCENTILE METRICS EXPLAINED:
    -----------------------------
    - p50 (median): Half of requests faster, half slower
    - p90: 90% of requests faster (10% slower outliers)
    - p95: 95% of requests faster (5% slower outliers)
    - p99: 99% of requests faster (1% slower outliers)

    WHY PERCENTILES OVER AVERAGES?
    -------------------------------
    Averages hide outliers. A few slow requests can make average look bad
    while most users have good experience.

    Example: 99 requests at 10ms, 1 request at 1000ms
    - Average: 19.9ms (misleading - most requests were 10ms!)
    - p95: 10ms (accurate - 95% of requests were fast)

    GOOGLE SRE BEST PRACTICE:
    -------------------------
    Monitor p99 latency for user-facing SLOs (Service Level Objectives).
    1% of users experiencing slow responses can still impact business.
    """

    avg_duration_ms: float = Field(
        ..., ge=0, description="Average duration in milliseconds across all executions"
    )
    p50_duration_ms: float = Field(
        ..., ge=0, description="50th percentile (median) duration in milliseconds"
    )
    p95_duration_ms: float = Field(
        ..., ge=0, description="95th percentile duration in milliseconds"
    )
    p99_duration_ms: float = Field(
        ..., ge=0, description="99th percentile duration in milliseconds"
    )
    min_duration_ms: float = Field(
        ..., ge=0, description="Minimum observed duration in milliseconds"
    )
    max_duration_ms: float = Field(
        ..., ge=0, description="Maximum observed duration in milliseconds"
    )
    execution_count: int = Field(..., ge=0, description="Total number of executions for this stage")

    @field_validator("max_duration_ms")
    @classmethod
    def validate_max_greater_than_min(cls, v: float, info) -> float:
        """
        Validate that max_duration >= min_duration.

        DEFENSIVE PROGRAMMING:
        ----------------------
        This validator catches data corruption bugs where max < min.
        Better to fail validation than return impossible statistics.
        """
        if "min_duration_ms" in info.data and v < info.data["min_duration_ms"]:
            raise ValueError(
                f"max_duration_ms ({v}) cannot be less than "
                f"min_duration_ms ({info.data['min_duration_ms']})"
            )
        return v


class CircuitBreakerStats(BaseModel):
    """
    Statistics for a single circuit breaker instance.

    MONITORING INSIGHTS:
    --------------------
    - High failure_count: External service having issues
    - state=OPEN: Service unavailable, requests being blocked
    - last_failure: Timestamp for incident correlation

    OPERATIONAL USE:
    ----------------
    1. Alerting: Alert when circuit opens (service down)
    2. Debugging: Correlate failures with external service incidents
    3. Capacity Planning: Track success/failure ratios over time
    """

    state: CircuitBreakerState = Field(..., description="Current circuit breaker state")
    failure_count: int = Field(default=0, ge=0, description="Number of consecutive failures")
    success_count: int = Field(default=0, ge=0, description="Number of consecutive successes")
    last_failure: str | None = Field(
        default=None,
        description="ISO 8601 timestamp of last failure (e.g., '2024-01-15T10:30:00Z')",
    )
    last_success: str | None = Field(default=None, description="ISO 8601 timestamp of last success")


class LatencyMetrics(BaseModel):
    """
    Latency metrics aggregated from Prometheus.

    NESTED STRUCTURE:
    -----------------
    stages: Dict mapping stage ID to percentile latencies
    overall_p99_ms: End-to-end request latency (p99)

    PROMETHEUS AGGREGATION:
    ----------------------
    These metrics are aggregated across ALL application instances
    using PromQL histogram_quantile() function.
    """

    stages: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Per-stage latency percentiles (p50, p90, p99)"
    )
    overall_p99_ms: float = Field(
        default=0.0, ge=0, description="Overall end-to-end p99 latency in milliseconds"
    )


class ConnectionMetrics(BaseModel):
    """
    Connection pool metrics.

    CONNECTION POOL PATTERN:
    ------------------------
    Reuses connections to avoid overhead of creating new connections.

    active: Currently in-use connections
    limit: Maximum allowed connections (prevents resource exhaustion)
    utilization_percent: active / limit * 100

    CAPACITY PLANNING:
    ------------------
    - < 50%: Plenty of headroom
    - 50-80%: Normal operation
    - 80-95%: Consider scaling up
    - > 95%: At capacity, new requests may queue or fail
    """

    active: int = Field(..., ge=0, description="Number of active connections")
    limit: int = Field(..., ge=1, description="Maximum allowed connections")
    utilization_percent: float = Field(
        default=0.0, ge=0, le=100, description="Connection pool utilization percentage"
    )
    state: ConnectionPoolState = Field(
        default=ConnectionPoolState.HEALTHY, description="Overall health state of connection pool"
    )


class ThroughputMetrics(BaseModel):
    """
    Request throughput and error rate metrics.

    RATE CALCULATION:
    -----------------
    Prometheus rate() function calculates per-second rate over time window:
    rate(metric[5m]) = increase in metric over 5 minutes / 300 seconds

    ERROR RATE BUDGET:
    ------------------
    Google SRE principle: Error budgets define acceptable failure rate.
    Example: 99.9% availability = 0.1% error rate budget
    """

    requests_per_sec: float = Field(
        default=0.0, ge=0, description="Request throughput (requests/second over 5min window)"
    )
    error_rate_percent: float = Field(
        default=0.0, ge=0, le=100, description="Error rate as percentage of total requests"
    )


class CacheMetrics(BaseModel):
    """
    Cache performance metrics.

    TWO-TIER CACHE ARCHITECTURE:
    ----------------------------
    L1: In-memory LRU cache (fast, limited capacity)
    L2: Redis cache (slower than L1, larger capacity, shared across instances)

    CACHE HIT RATE:
    ---------------
    hit_rate = hits / (hits + misses) * 100

    Target: > 80% hit rate for good cache effectiveness
    < 50% hit rate suggests cache size too small or poor key design

    PERFORMANCE IMPACT:
    -------------------
    Cache hit: ~0.1-1ms (L1) or ~2-5ms (L2)
    Cache miss + LLM call: ~500-2000ms
    Speedup: 100-1000x for cached responses!
    """

    hit_rate_percent: float = Field(
        default=0.0, ge=0, le=100, description="Overall cache hit rate percentage"
    )
    l1_hits_per_sec: float = Field(
        default=0.0, ge=0, description="L1 (in-memory) cache hits per second"
    )
    l2_hits_per_sec: float = Field(
        default=0.0, ge=0, description="L2 (Redis) cache hits per second"
    )


class QueueMetrics(BaseModel):
    """
    Message queue metrics for failover mechanism.

    QUEUE FAILOVER PATTERN:
    -----------------------
    When connection pool is exhausted, requests are queued instead of rejected.
    Worker processes drain the queue when capacity becomes available.

    depth: Number of requests waiting in queue
    produce_failures_per_sec: Rate of failed queue insertions

    MONITORING:
    -----------
    - depth > 0: System under load, using queue failover
    - depth increasing: Not draining fast enough, may need more workers
    - produce_failures > 0: Queue system having issues
    """

    depth: int = Field(default=0, ge=0, description="Current queue depth (requests waiting)")
    produce_failures_per_sec: float = Field(
        default=0.0, ge=0, description="Rate of failed queue insertions"
    )


class ConnectionPoolStats(BaseModel):
    """
    Detailed connection pool statistics.

    Used by /streaming-metrics endpoint for dashboard visualization.
    """

    active: int = Field(ge=0, description="Active connections")
    max: int = Field(ge=1, description="Maximum connections")
    utilization_percent: float = Field(ge=0, le=100, description="Utilization percentage")
    state: str = Field(description="Health state (healthy/degraded/exhausted)")


class CacheStats(BaseModel):
    """
    Detailed cache statistics.

    L1_STATS STRUCTURE:
    -------------------
    hit_rate: Percentage of L1 cache hits
    size: Current number of entries in L1 cache
    max_size: Maximum capacity of L1 cache
    """

    l1: dict[str, Any] = Field(default_factory=dict, description="L1 (in-memory) cache statistics")


class StageTimings(BaseModel):
    """
    Timing percentiles for processing stages.

    Used by dashboard to visualize bottlenecks across stages.
    If stage 3 (LLM Call) has high p99, external provider is slow.
    If stage 1 (Cache Lookup) has high p99, cache system needs optimization.
    """

    p50_duration_ms: float = Field(ge=0)
    p90_duration_ms: float = Field(ge=0)
    p95_duration_ms: float = Field(ge=0)
    p99_duration_ms: float = Field(ge=0)
    avg_duration_ms: float = Field(ge=0)
    execution_count: int = Field(ge=0)


# ============================================================================
# TOP-LEVEL RESPONSE MODELS
# ============================================================================
# These are the actual models returned by API endpoints.
# They compose the smaller models defined above.


class ExecutionStatsResponse(BaseModel):
    """
    Response model for GET /admin/execution-stats endpoint.

    USAGE:
    ------
    @router.get("/execution-stats", response_model=ExecutionStatsResponse)
    async def get_execution_statistics():
        return ExecutionStatsResponse(stages={...})

    BENEFITS:
    ---------
    - FastAPI validates response matches this schema
    - Generates OpenAPI documentation automatically
    - Type checking in IDE for response construction
    """

    stages: dict[str, StageStatistics] = Field(..., description="Map of stage ID to statistics")


class CircuitBreakerResponse(BaseModel):
    """
    Response model for GET /admin/circuit-breakers endpoint.

    Returns map of circuit breaker name (e.g., "openai_provider") to stats.
    """

    circuit_breakers: dict[str, CircuitBreakerStats] = Field(
        default_factory=dict, description="Map of circuit breaker name to statistics"
    )


class PrometheusStatsResponse(BaseModel):
    """
    Response model for GET /admin/prometheus-stats endpoint.

    AGGREGATION ACROSS INSTANCES:
    -----------------------------
    All metrics are aggregated across multiple application instances
    using Prometheus PromQL queries with sum/avg aggregations.

    This gives a cluster-wide view, not single-instance view.
    """

    prometheus_available: bool = Field(
        ..., description="Whether Prometheus is reachable and healthy"
    )
    latency: LatencyMetrics = Field(..., description="Latency metrics across all stages")
    connections: ConnectionMetrics = Field(..., description="Connection pool metrics")
    throughput: ThroughputMetrics = Field(..., description="Request throughput and error rates")
    cache: CacheMetrics = Field(..., description="Cache performance metrics")
    queue: QueueMetrics = Field(..., description="Message queue metrics")
    circuit_breakers: dict[str, str] = Field(
        default_factory=dict, description="Map of provider name to circuit breaker state"
    )


class StreamingMetricsResponse(BaseModel):
    """
    Response model for GET /admin/streaming-metrics endpoint.

    DASHBOARD-FOCUSED:
    ------------------
    This endpoint provides a consolidated view for the performance dashboard,
    combining connection pool, cache, and stage timing metrics.
    """

    connection_pool: ConnectionPoolStats = Field(..., description="Connection pool statistics")
    cache: CacheStats = Field(..., description="Cache statistics")
    stages: dict[str, StageTimings] = Field(..., description="Per-stage timing statistics")


class ConfigResponse(BaseModel):
    """
    Response model for GET/PUT /admin/config endpoints.

    RUNTIME CONFIGURATION:
    ----------------------
    These are feature flags that can be toggled without restarting the service.

    USE_FAKE_LLM: Use mock LLM for testing (no API calls, instant responses)
    ENABLE_CACHING: Enable/disable response caching
    QUEUE_TYPE: Message queue implementation (redis/kafka)

    OPERATIONAL USE:
    ----------------
    - Disable caching during debugging
    - Enable fake LLM for load testing without API costs
    - Switch queue types for A/B testing
    """

    USE_FAKE_LLM: bool = Field(..., description="Whether to use fake LLM provider for testing")
    ENABLE_CACHING: bool = Field(..., description="Whether response caching is enabled")
    QUEUE_TYPE: str = Field(..., description="Message queue type (redis/kafka)")


class ConfigUpdateResponse(BaseModel):
    """
    Response model for PUT /admin/config endpoint.

    CONFIRMATION PATTERN:
    ---------------------
    Always return the current state after update to confirm changes took effect.
    Client can verify update succeeded by checking current_config matches request.
    """

    status: str = Field(
        default="updated", description="Update status (always 'updated' on success)"
    )
    current_config: ConfigResponse = Field(..., description="Current configuration after update")


# ============================================================================
# EXPORTS
# ============================================================================
# All models available for import from this module

__all__ = [
    # Enums
    "ProcessingStage",
    "CircuitBreakerState",
    "ConnectionPoolState",
    # Nested Models
    "StageStatistics",
    "CircuitBreakerStats",
    "LatencyMetrics",
    "ConnectionMetrics",
    "ThroughputMetrics",
    "CacheMetrics",
    "QueueMetrics",
    "ConnectionPoolStats",
    "CacheStats",
    "StageTimings",
    # Response Models
    "ExecutionStatsResponse",
    "CircuitBreakerResponse",
    "PrometheusStatsResponse",
    "StreamingMetricsResponse",
    "ConfigResponse",
    "ConfigUpdateResponse",
]
