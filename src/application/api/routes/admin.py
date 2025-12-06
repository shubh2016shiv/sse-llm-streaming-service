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

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.core.observability.execution_tracker import get_tracker
from src.core.resilience.circuit_breaker import get_circuit_breaker_manager
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

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
# STATISTICS ENDPOINTS
# ============================================================================


@router.get("/execution-stats")
async def get_execution_statistics():
    """
    Retrieve execution statistics by processing stage.

    EXECUTION TRACKING:
    -------------------
    This application tracks performance metrics for each stage of request
    processing (cache lookup, provider selection, LLM call, etc.).

    This endpoint returns statistics like:
    - Average execution time per stage
    - Min/max execution times
    - Number of executions
    - Success/failure rates

    USE CASES:
    ----------
    - Identify performance bottlenecks
    - Monitor stage-specific degradation
    - Capacity planning
    - SLA compliance verification

    FASTAPI AUTOMATIC JSON SERIALIZATION:
    -------------------------------------
    Notice we return a plain Python dict. FastAPI automatically:
    1. Serializes it to JSON
    2. Sets Content-Type: application/json header
    3. Handles special types (datetime, UUID, etc.)

    You can also return:
    - Pydantic models (validated and serialized)
    - Lists, tuples (converted to JSON arrays)
    - None (returns null)

    Returns:
        dict: Statistics for each processing stage

    Example Response:
        {
            "1": {"avg_time": 0.05, "count": 1000, ...},
            "2": {"avg_time": 0.10, "count": 950, ...},
            ...
        }
    """
    # Get the global execution tracker singleton
    tracker = get_tracker()

    # Define the stages we want statistics for
    # These correspond to different phases of request processing
    stages = ["1", "2", "2.1", "2.2", "3", "4", "5", "6"]
    stats = {}

    # Collect statistics for each stage
    # This is a simple loop that builds a dictionary
    for stage in stages:
        stats[stage] = tracker.get_stage_statistics(stage)

    return stats


@router.get("/circuit-breakers")
async def get_circuit_breaker_statistics():
    """
    Retrieve circuit breaker states and statistics.

    CIRCUIT BREAKER PATTERN:
    ------------------------
    Circuit breakers prevent cascading failures by:
    1. Monitoring failure rates of external calls
    2. "Opening" (blocking calls) when failures exceed threshold
    3. Periodically testing if the service recovered ("half-open")
    4. "Closing" (allowing calls) when service is healthy again

    States:
    - CLOSED: Normal operation, calls go through
    - OPEN: Too many failures, calls are blocked
    - HALF_OPEN: Testing if service recovered

    WHY MONITOR CIRCUIT BREAKERS?
    ------------------------------
    - Detect when external services are failing
    - Understand system resilience behavior
    - Alert when circuit breakers open frequently
    - Capacity planning (how often do we hit limits?)

    This endpoint returns:
    - Current state of each circuit breaker
    - Failure counts
    - Success counts
    - Last state change timestamp

    Returns:
        dict: Circuit breaker states and statistics

    Example Response:
        {
            "openai_provider": {
                "state": "closed",
                "failure_count": 2,
                "success_count": 1000,
                "last_failure": "2024-01-15T10:30:00Z"
            },
            ...
        }
    """
    circuit_breaker_manager = get_circuit_breaker_manager()
    return circuit_breaker_manager.get_all_stats()


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


@router.post("/config")
async def update_configuration(request: UpdateConfigRequest):
    """
    Update runtime configuration (feature flags).

    RUNTIME CONFIGURATION:
    ----------------------
    This endpoint allows changing configuration without restarting the app.

    How it works:
    1. Client sends new configuration values
    2. We update the settings singleton
    3. Dependent components react to the changes
    4. New behavior takes effect immediately

    USE CASES:
    ----------
    - Feature flags: Enable/disable features in production
    - A/B testing: Route users to different implementations
    - Emergency switches: Disable expensive features during incidents
    - Experimentation: Try different configurations

    CAUTION:
    --------
    In production, this endpoint should:
    - Require authentication (admin only)
    - Log all changes for audit
    - Validate configuration values
    - Potentially require confirmation for dangerous changes

    DEPENDENCY RE-INITIALIZATION:
    -----------------------------
    Notice when USE_FAKE_LLM changes, we re-register providers.
    This is because the provider factory needs to know whether to
    create real or fake LLM clients.

    Some configuration changes require restarting components.
    Others take effect immediately.

    Args:
        request: Configuration update request (partial updates allowed)

    Returns:
        dict: Updated configuration values

    Example Request:
        POST /admin/config
        {"USE_FAKE_LLM": true, "ENABLE_CACHING": false}

    Example Response:
        {
            "status": "updated",
            "current_config": {
                "USE_FAKE_LLM": true,
                "ENABLE_CACHING": false,
                "QUEUE_TYPE": "redis"
            }
        }
    """
    # Import here to avoid circular dependencies
    # This is a common pattern for admin endpoints that modify global state
    from src.core.config.settings import get_settings

    settings = get_settings()

    # Update each field if provided in the request
    # The 'is not None' check allows distinguishing between:
    # - Field not provided (None, don't update)
    # - Field explicitly set to False (update to False)

    if request.USE_FAKE_LLM is not None:
        settings.USE_FAKE_LLM = request.USE_FAKE_LLM

        # Re-register providers with new fake/real setting
        # This ensures new requests use the correct provider type
        from src.core.config.bootstrap import register_providers

        register_providers()

    if request.ENABLE_CACHING is not None:
        settings.ENABLE_CACHING = request.ENABLE_CACHING

    if request.QUEUE_TYPE is not None:
        settings.QUEUE_TYPE = request.QUEUE_TYPE

    # Return confirmation with current state
    return {
        "status": "updated",
        "current_config": {
            "USE_FAKE_LLM": settings.USE_FAKE_LLM,
            "ENABLE_CACHING": settings.ENABLE_CACHING,
            "QUEUE_TYPE": settings.QUEUE_TYPE,
        },
    }


@router.get("/config")
async def get_configuration():
    """
    Retrieve current configuration (feature flags).

    CONFIGURATION INSPECTION:
    -------------------------
    This endpoint returns the current runtime configuration.
    Useful for:
    - Debugging (what settings are active?)
    - Dashboards (show current feature flag states)
    - Verification (confirm configuration changes took effect)

    SIMPLE GET ENDPOINT:
    --------------------
    This is a straightforward GET endpoint that:
    1. Gets the settings singleton
    2. Extracts relevant configuration values
    3. Returns them as a dictionary
    4. FastAPI automatically serializes to JSON

    No request body, no parameters, just returns current state.

    Returns:
        dict: Current configuration values

    Example Response:
        {
            "USE_FAKE_LLM": false,
            "ENABLE_CACHING": true,
            "QUEUE_TYPE": "redis"
        }
    """
    from src.core.config.settings import get_settings

    settings = get_settings()

    return {
        "USE_FAKE_LLM": settings.USE_FAKE_LLM,
        "ENABLE_CACHING": settings.ENABLE_CACHING,
        "QUEUE_TYPE": settings.QUEUE_TYPE,
    }
