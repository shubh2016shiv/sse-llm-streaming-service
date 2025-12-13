"""
Monitoring Exceptions

Exception types for monitoring infrastructure components like Prometheus,
Grafana, and other observability tools.

ARCHITECTURAL DECISION:
----------------------
These exceptions provide explicit error handling for monitoring operations,
replacing silent `None` returns with descriptive errors that:

1. **Enable Better Debugging**: Stack traces show exactly where failures occur
2. **Support Error Recovery**: Callers can catch specific error types
3. **Improve Observability**: Errors can be logged with full context
4. **Document Failure Modes**: Exception types serve as API documentation

DESIGN PATTERN:
---------------
Following the project's exception hierarchy:
- All exceptions inherit from SSEBaseError
- PrometheusError is the base for all Prometheus-related errors
- Specific subclasses for different failure categories

Author: System Architect
Date: 2025-12-13
"""

from src.core.exceptions.base import SSEBaseError


class PrometheusError(SSEBaseError):
    """
    Base exception for all Prometheus-related operations.

    Use this as a catch-all for Prometheus errors when you don't need
    to distinguish between specific failure types.

    Example:
        try:
            result = await prometheus_client.query("up")
        except PrometheusError as e:
            logger.error("Prometheus operation failed", error=e.to_dict())
    """

    pass


class PrometheusConnectionError(PrometheusError):
    """
    Raised when connection to Prometheus server fails.

    COMMON CAUSES:
    --------------
    - Prometheus server is down or unreachable
    - Network connectivity issues
    - Incorrect base URL configuration
    - Firewall blocking the connection
    - DNS resolution failure

    RECOVERY STRATEGIES:
    --------------------
    1. Check if Prometheus container is running
    2. Verify network connectivity (docker network)
    3. Check PROMETHEUS_URL environment variable
    4. Wait for circuit breaker cooldown

    Example:
        try:
            await client.query("up")
        except PrometheusConnectionError as e:
            logger.warning("Prometheus unavailable, using fallback data")
            return default_metrics()
    """

    pass


class PrometheusQueryError(PrometheusError):
    """
    Raised when a PromQL query execution fails.

    This exception is raised when Prometheus is reachable but the query
    itself fails (e.g., syntax error, invalid metric name).

    COMMON CAUSES:
    --------------
    - PromQL syntax error
    - Invalid metric name
    - Query timeout (query too expensive)
    - HTTP 4xx/5xx response

    DEBUGGING:
    ----------
    1. Check the promql attribute for the failing query
    2. Test query directly in Prometheus UI
    3. Verify metric exists: /api/v1/label/__name__/values

    Example:
        try:
            result = await client.query("rate(invalid_metric[5m])")
        except PrometheusQueryError as e:
            logger.error("Query failed", promql=e.details.get("promql"))
    """

    pass


class PrometheusExtractionError(PrometheusError):
    """
    Raised when extracting values from Prometheus response fails.

    Prometheus returns data in specific formats (scalar, vector, matrix).
    This exception indicates the response couldn't be parsed as expected.

    COMMON CAUSES:
    --------------
    - Unexpected response format (resultType mismatch)
    - Empty result set (no data for time range)
    - Non-numeric value in result
    - NaN or Inf values (not JSON-serializable)

    DEBUGGING:
    ----------
    1. Check the raw response in exception details
    2. Verify the expected result type matches query type
    3. Check if metric is emitting data (scrape interval)

    WHY THIS MATTERS:
    -----------------
    Silent None returns hide data quality issues. Explicit exceptions
    surface problems early, making debugging faster.

    Example:
        try:
            value = client.extract_scalar_value(response)
        except PrometheusExtractionError as e:
            logger.warning(
                "Failed to extract metric",
                result_type=e.details.get("result_type"),
                expected="scalar"
            )
    """

    pass
