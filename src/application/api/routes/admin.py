"""
Admin Routes - Educational Documentation
=========================================

WHAT ARE ADMIN ENDPOINTS?
--------------------------
Admin endpoints provide operational capabilities for managing and monitoring
the application. They typically include:

1. Metrics: Performance and usage statistics (Prometheus, StatsD, etc.)
2. Configuration: Runtime configuration updates
3. Statistics: Execution stats, circuit breaker states, etc.
4. Debugging: Internal state inspection

SECURITY CONSIDERATIONS:
------------------------
In production, admin endpoints should be:
- Protected by authentication/authorization
- Exposed on a separate port (not public-facing)
- Rate-limited to prevent abuse
- Logged for audit trails

For this application, we'll focus on the educational aspects of the endpoints.

PROMETHEUS METRICS:
-------------------
Prometheus is a popular monitoring system that:
- Scrapes metrics from HTTP endpoints (pull model)
- Stores time-series data
- Provides powerful querying (PromQL)
- Integrates with alerting (Alertmanager)
- Works with visualization tools (Grafana)

Metrics format:
    # HELP metric_name Description of the metric
    # TYPE metric_name counter
    metric_name{label="value"} 123.45

This module contains administrative and monitoring endpoints.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

# Import new models and services
from src.application.api.models.admin import (
    CircuitBreakerResponse,
    CircuitBreakerStats,
    ConfigResponse,
    ConfigUpdateResponse,
    ExecutionStatsResponse,
    ProcessingStage,
    PrometheusStatsResponse,
    StageStatistics,
    StreamingMetricsResponse,
)
from src.application.services.config_service import get_config_service
from src.application.services.metrics_service import get_metrics_service
from src.core.observability.execution_tracker import get_tracker
from src.core.resilience.circuit_breaker import get_circuit_breaker_manager
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

# Structured logging
logger = structlog.get_logger(__name__)

# ============================================================================
# ROUTER SETUP
# ============================================================================
# Admin router for operational endpoints
# These endpoints are typically used by:
# - Monitoring systems (Prometheus, Datadog, etc.)
# - Operations teams (debugging, configuration)
# - Dashboards (performance visualization)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================================================
# AUTHENTICATION PLACEHOLDER
# ============================================================================
# TODO: Implement authentication in the future
# For now, this is a placeholder that always succeeds
# When ready to add auth, replace this with actual token verification


async def verify_admin_access() -> None:
    """
    Placeholder for admin authentication.

    FUTURE IMPLEMENTATION:
    ----------------------
    When ready to add authentication:
    1. Add HTTPBearer dependency to extract token
    2. Verify token against auth service
    3. Check user has admin role
    4. Raise HTTPException(403) if unauthorized

    Example:
        from fastapi.security import HTTPBearer

        security = HTTPBearer()

        async def verify_admin_access(
            credentials: HTTPAuthorizationCredentials = Depends(security)
        ) -> None:
            if not is_valid_admin_token(credentials.credentials):
                raise HTTPException(status_code=403, detail="Admin access required")
    """
    pass  # No-op for now


# ============================================================================
# STATISTICS ENDPOINTS
# ============================================================================


@router.get(
    "/execution-stats",
    response_model=ExecutionStatsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def get_execution_statistics():
    """
    Retrieve execution statistics by processing stage.

    EXECUTION TRACKING:
    -------------------
    This application tracks performance metrics for each stage of request
    processing (cache lookup, provider selection, LLM call, etc.).

    IMPROVEMENTS IN THIS REFACTORED VERSION:
    -----------------------------------------
    1. **Type Safety**: Returns ExecutionStatsResponse (Pydantic model)
    2. **Constants**: Uses ProcessingStage enum instead of magic strings
    3. **Error Handling**: Catches exceptions and returns proper HTTP errors
    4. **Documentation**: Auto-generated OpenAPI schema from response model

    Returns:
        ExecutionStatsResponse: Statistics for each processing stage

    Raises:
        HTTPException: 500 if unable to retrieve statistics
    """
    try:
        logger.debug("get_execution_stats_started")

        # Get the global execution tracker singleton
        tracker = get_tracker()

        # Use enum for type-safe stage IDs
        # BEFORE: stages = ["1", "2", ...] (magic strings)
        # AFTER: Uses ProcessingStage enum (type-safe, documented)
        stages = [stage.value for stage in ProcessingStage]
        stats_dict = {}

        # Collect statistics for each stage
        for stage in stages:
            raw_stats = tracker.get_stage_statistics(stage)

            # Convert to Pydantic model for validation
            stats_dict[stage] = StageStatistics(**raw_stats)

        logger.debug("get_execution_stats_completed", stages_returned=len(stats_dict))

        return ExecutionStatsResponse(stages=stats_dict)

    except Exception as e:
        logger.error("get_execution_stats_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve execution statistics",
        )


@router.get(
    "/circuit-breakers",
    response_model=CircuitBreakerResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def get_circuit_breaker_statistics():
    """
    Retrieve circuit breaker states and statistics.

    CIRCUIT BREAKER PATTERN:
    ------------------------
    Circuit breakers prevent cascading failures by "failing fast".

    CRITICAL BUG FIX:
    -----------------
    BEFORE: Missing `await` - returned coroutine object instead of data!
    AFTER: Properly awaits async call to get actual statistics

    IMPROVEMENTS:
    -------------
    1. **Bug Fix**: Added missing `await` keyword
    2. **Type Safety**: Returns CircuitBreakerResponse model
    3. **Error Handling**: Catches and logs errors gracefully

    Returns:
        CircuitBreakerResponse: Circuit breaker states and statistics

    Raises:
        HTTPException: 500 if unable to retrieve circuit breaker stats
    """
    try:
        logger.debug("get_circuit_breaker_stats_started")

        circuit_breaker_manager = get_circuit_breaker_manager()

        # BUG FIX: Added await (was missing in original code)
        # Without await, this returns a coroutine object, not the actual data!
        raw_stats = await circuit_breaker_manager.get_all_stats()

        # Convert to typed response model
        cb_models = {}
        for name, stats in raw_stats.items():
            cb_models[name] = CircuitBreakerStats(**stats)

        logger.debug("get_circuit_breaker_stats_completed", circuit_breaker_count=len(cb_models))

        return CircuitBreakerResponse(circuit_breakers=cb_models)

    except Exception as e:
        logger.error("get_circuit_breaker_stats_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve circuit breaker statistics",
        )


# ============================================================================
# METRICS ENDPOINTS
# ============================================================================


@router.get("/metrics")
async def get_prometheus_metrics():
    """
    Expose metrics in Prometheus text format for scraping.

    PROMETHEUS INTEGRATION:
    -----------------------
    Prometheus uses a "pull" model where it periodically scrapes
    metrics from HTTP endpoints (typically /metrics).

    The metrics are in a specific text format:
        # HELP http_requests_total Total HTTP requests
        # TYPE http_requests_total counter
        http_requests_total{method="GET",status="200"} 1234

    FASTAPI Response CLASS:
    -----------------------
    We use the Response class to return raw text instead of JSON.

    Response parameters:
    - content: The raw response body (string or bytes)
    - media_type: Content-Type header value

    Why not just return a string?
    - FastAPI would JSON-serialize it (add quotes)
    - We need raw text for Prometheus to parse
    - We need to set the correct Content-Type

    The Response class gives us full control over:
    - Response body
    - Headers
    - Status code
    - Media type

    PROMETHEUS SCRAPING:
    --------------------
    To use this endpoint with Prometheus, add to prometheus.yml:

        scrape_configs:
          - job_name: 'sse-service'
            static_configs:
              - targets: ['localhost:8000']
            metrics_path: '/admin/metrics'
            scrape_interval: 15s

    Returns:
        Response: Prometheus-formatted metrics as plain text

    Example Response (plain text):
        # HELP sse_requests_total Total SSE requests
        # TYPE sse_requests_total counter
        sse_requests_total{status="success"} 1234
        sse_requests_total{status="error"} 56
    """
    metrics_collector = get_metrics_collector()

    # Get metrics in Prometheus text format
    # This is a string like "metric_name{labels} value\n..."
    metrics_text = metrics_collector.get_prometheus_metrics()

    # Get the appropriate Content-Type for Prometheus
    # Typically "text/plain; version=0.0.4"
    content_type = metrics_collector.get_content_type()

    # Return as raw text response (not JSON)
    return Response(content=metrics_text, media_type=content_type)


@router.get(
    "/prometheus-stats",
    response_model=PrometheusStatsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def get_prometheus_statistics():
    """
    Aggregate Prometheus metrics for dashboard consumption.

    MAJOR REFACTORING:
    ------------------
    BEFORE: 210 lines of complex PromQL queries in this function
    AFTER: Delegates to MetricsService (separation of concerns)

    IMPROVEMENTS:
    -------------
    1. **Reduced Cognitive Load**: Route is now 20 lines (was 210+)
    2. **Separation of Concerns**: Business logic in service, HTTP in route
    3. **Testability**: Can test MetricsService without HTTP mocking
    4. **Caching**: Service caches results for 30 seconds (less Prometheus load)
    5. **Error Handling**: Graceful degradation when Prometheus unavailable
    6. **Type Safety**: Returns PrometheusStatsResponse model

    ARCHITECTURE:
    ------------
    Dashboard → This Route → MetricsService → PrometheusClient → Prometheus

    Returns:
        PrometheusStatsResponse: All aggregated metrics

    Raises:
        HTTPException: 503 if Prometheus unavailable
        HTTPException: 500 for other errors
    """
    try:
        logger.debug("get_prometheus_stats_started")

        # Delegate to MetricsService (handles all complex Prometheus logic)
        # COGNITIVE LOAD REDUCTION:
        # - No PromQL queries here (moved to service)
        # - No aggregation logic here (moved to service)
        # - No error handling for individual queries (service handles it)
        # Route focuses only on HTTP concerns
        service = get_metrics_service()
        result = await service.get_aggregated_metrics()

        logger.debug(
            "get_prometheus_stats_completed",
            prometheus_available=result.prometheus_available,
            stages_with_latency=len(result.latency.stages),
        )

        return result

    except Exception as e:
        logger.error("get_prometheus_stats_failed", error=str(e), error_type=type(e).__name__)

        # Check if Prometheus is specifically unavailable
        if "prometheus" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Prometheus service unavailable",
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve Prometheus statistics",
        )


# NOTE: The following helper functions are now in MetricsService
# This eliminates 180+ lines of complex query logic from this route file!
# See: src/application/services/metrics_service.py
# - _safe_query(): Query and extract scalar values
# - _safe_vector_query(): Query and extract vector values
# - _get_latency_percentiles(): Get percentiles for a stage
# - get_latency_metrics(): Aggregate all latency metrics
# - get_connection_metrics(): Get connection pool stats
# - get_throughput_metrics(): Get request throughput
# - get_cache_metrics(): Get cache performance
# - get_queue_metrics(): Get queue depth
# - get_circuit_breaker_states(): Get CB states

# ============================================================================
# The rest of the Prometheus stats logic (lines 295-458) is now handled by
# MetricsService.get_aggregated_metrics(). This dramatically simplifies
# this route file and makes the business logic testable independently.
# ============================================================================


# ============================================================================
# CONFIGURATION ENDPOINTS
# ============================================================================
# These endpoints allow runtime configuration changes without restarting
# the application. Useful for:
# - Feature flags (enable/disable features)
# - A/B testing
# - Emergency switches (disable expensive features)
# - Experimentation (try different queue types, etc.)


class UpdateConfigRequest(BaseModel):
    """
    Request model for configuration updates.

    OPTIONAL FIELDS IN PYDANTIC:
    ----------------------------
    All fields have '| None = None' which means:
    - The field can be the specified type OR None
    - Default value is None if not provided
    - The field is optional in the request

    This allows partial updates:
    - Send only the fields you want to change
    - Other fields remain unchanged

    Example requests:
        {"USE_FAKE_LLM": true}  # Only update this field
        {"ENABLE_CACHING": false, "QUEUE_TYPE": "kafka"}  # Update two fields
    """

    USE_FAKE_LLM: bool | None = None  # Use fake LLM for testing
    ENABLE_CACHING: bool | None = None  # Enable/disable response caching
    QUEUE_TYPE: str | None = None  # Message queue type (redis/kafka)


@router.get(
    "/streaming-metrics",
    response_model=StreamingMetricsResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def get_streaming_metrics():
    """
    Get consolidated streaming performance metrics for dashboard.

    This endpoint aggregates:
    - Connection pool statistics (utilization, state)
    - Cache performance (hit rates, sizes)
    - Stage timing percentiles (p50, p90, p95, p99)

    Returns:
        dict: Comprehensive streaming metrics

    Example Response:
        {
            "connection_pool": {
                "total_connections": 15,
                "max_connections": 100,
                "utilization_percent": 15.0,
                "state": "healthy"
            },
            "cache_stats": {
                "l1_hit_rate": 0.68,
                "l1_size": 234,
                "l1_max_size": 1000
            },
            "stage_timings": {
                "1": {"p50": 2.1, "p90": 4.5, "p95": 6.2, "p99": 10.1},
                ...
            }
        }
    """
    # Import dependencies
    from src.core.resilience.connection_pool_manager import get_connection_pool_manager
    from src.infrastructure.cache.cache_manager import get_cache_manager

    # Get connection pool stats
    pool_manager = get_connection_pool_manager()
    pool_stats = await pool_manager.get_stats()

    # Get cache manager
    cache_manager = get_cache_manager()
    cache_stats = cache_manager.get_cache_stats()

    # Get execution tracker for stage timings
    tracker = get_tracker()
    stages = ["1", "2", "2.1", "2.2", "3", "4", "5", "6"]
    stage_timings = {}

    for stage in stages:
        stats = tracker.get_stage_statistics(stage)
        stage_timings[stage] = {
            "p50_duration_ms": stats["p50_duration_ms"],
            "p90_duration_ms": stats.get("p90_duration_ms", 0),  # p90 not in current implementation
            "p95_duration_ms": stats["p95_duration_ms"],
            "p99_duration_ms": stats["p99_duration_ms"],
            "avg_duration_ms": stats["avg_duration_ms"],
            "execution_count": stats["execution_count"],
        }

    # Consolidate response
    return {
        "connection_pool": {
            "active": pool_stats.get("total_connections", 0),
            "max": pool_stats.get("max_connections", 100),
            "utilization_percent": pool_stats.get("utilization_percent", 0),
            "state": pool_stats.get("state", "unknown"),
        },
        "cache": {
            "l1": {
                "hit_rate": cache_stats["l1_stats"]["hit_rate"],
                "size": cache_stats["l1_stats"]["size"],
                "max_size": cache_stats["l1_stats"]["max_size"],
            }
        },
        "stages": stage_timings,
    }


@router.put(
    "/config",
    response_model=ConfigUpdateResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def update_configuration(request: UpdateConfigRequest):
    """
    Update runtime configuration (feature flags).

    REFACTORED VERSION:
    -------------------
    BEFORE: 75 lines of business logic in route handler
    AFTER: Delegates to ConfigService (separation of concerns)

    IMPROVEMENTS:
    -------------
    1. **Service Layer**: Business logic in ConfigService
    2. **Error Handling**: Comprehensive try/except with logging
    3. **Validation**: ConfigService validates queue types
    4. **Audit Logging**: All changes logged with context
    5. **Type Safety**: Returns ConfigUpdateResponse model

    Args:
        request: Configuration update request (partial updates allowed)

    Returns:
        ConfigUpdateResponse: Status and current configuration

    Raises:
        HTTPException: 400 for validation errors, 500 for other errors
    """
    try:
        logger.info(
            "config_update_requested",
            changes={k: v for k, v in request.dict().items() if v is not None},
        )

        # Delegate to ConfigService (handles validation, logging, side effects)
        service = get_config_service()
        result = await service.update_config(request)

        logger.info("config_update_completed", status=result.status)

        return result

    except ValueError as e:
        # Validation errors (e.g., invalid queue type)
        logger.warning("config_update_validation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid configuration: {str(e)}"
        )

    except Exception as e:
        logger.error("config_update_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration",
        )


@router.get(
    "/config",
    response_model=ConfigResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_admin_access)],
)
async def get_configuration():
    """
    Retrieve current configuration (feature flags).

    REFACTORED VERSION:
    -------------------
    BEFORE: 40 lines directly accessing settings
    AFTER: Delegates to ConfigService (consistency with other endpoints)

    IMPROVEMENTS:
    -------------
    1. **Service Layer**: Uses ConfigService.get_current_config()
    2. **Error Handling**: Comprehensive try/except with logging
    3. **Type Safety**: Returns ConfigResponse model
    4. **Consistency**: Matches pattern of all other endpoints

    Returns:
        ConfigResponse: Current configuration values

    Raises:
        HTTPException: 500 if unable to retrieve configuration
    """
    try:
        logger.debug("get_config_started")

        # Delegate to ConfigService for consistency
        service = get_config_service()
        result = service.get_current_config()

        logger.debug(
            "get_config_completed",
            use_fake_llm=result.USE_FAKE_LLM,
            enable_caching=result.ENABLE_CACHING,
            queue_type=result.QUEUE_TYPE,
        )

        return result

    except Exception as e:
        logger.error("get_config_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration",
        )
