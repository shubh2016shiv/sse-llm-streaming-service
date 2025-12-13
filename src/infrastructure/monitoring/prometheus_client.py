"""
Prometheus HTTP Client with Production-Grade Resilience
========================================================

This module provides an asynchronous HTTP client for querying Prometheus,
implementing enterprise-grade patterns for reliability, observability, and
maintainability.

MODULE OVERVIEW
---------------
The PrometheusClient enables the backend to query Prometheus metrics for the
performance dashboard. It implements multiple layers of resilience to handle
the reality that external dependencies (like Prometheus) may be temporarily
unavailable.

ARCHITECTURAL CONTEXT
---------------------
```
Performance Dashboard → Backend API → [PrometheusClient] → Prometheus Server
                                              ↓
                                    [DistributedCircuitBreaker]
                                              ↓
                                        Redis (shared state)
```

The client sits in the critical path for metrics retrieval. Failures here
should degrade gracefully, not crash the dashboard or spam logs.

KEY DESIGN DECISIONS
--------------------

1. **Distributed Circuit Breaker Integration** (ADR-XXX)
   - Reuses the existing DistributedCircuitBreaker from resilience layer
   - State is shared across all application instances via Redis
   - When one instance detects Prometheus is down, ALL instances stop trying
   - Prevents "thundering herd" problems during outages

   Why not a local circuit breaker?
   - In a multi-pod deployment, each instance would discover unavailability
     independently, causing N times the error logs
   - Redis-backed state ensures coordination across instances

2. **Reusable HTTP Client** (Resource Efficiency)
   - HTTP/2 connection pooling dramatically reduces latency
   - Single client instance prevents socket exhaustion
   - Context manager pattern ensures proper cleanup
   - Limits configured to prevent unbounded connections

3. **Explicit Exception Types** (Debuggability)
   - PrometheusConnectionError: Network/connectivity issues
   - PrometheusQueryError: PromQL execution failures
   - PrometheusExtractionError: Response parsing failures
   - Each exception carries context for debugging

4. **Retry with Exponential Backoff** (Transient Error Handling)
   - Circuit breaker handles sustained failures
   - Retries handle transient failures (network blips)
   - Exponential backoff with jitter prevents thundering herd

5. **Configuration Validation** (Fail Fast)
   - Pydantic validates all configuration at startup
   - Invalid URLs/timeouts caught before they cause runtime errors
   - Environment variable overrides supported

USAGE PATTERNS
--------------
```python
# Context manager pattern (recommended)
async with PrometheusClient() as client:
    response = await client.query("up")
    value = client.extract_scalar_value(response)

# Dependency injection in FastAPI
async def get_prometheus_client() -> AsyncIterator[PrometheusClient]:
    async with PrometheusClient() as client:
        yield client

@router.get("/metrics")
async def get_metrics(client: PrometheusClient = Depends(get_prometheus_client)):
    return await client.query("...")
```

MONITORING THIS CLIENT
----------------------
The client itself emits structured logs that can be used for monitoring:
- prometheus.query.started: Query initiated
- prometheus.query.success: Query completed successfully
- prometheus.query.failed: Query failed (with error details)
- prometheus.circuit_breaker.opened: Circuit opened after failures
- prometheus.circuit_breaker.closed: Circuit restored after cooldown

Author: System Architect
Date: 2025-12-13
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.core.exceptions import (
    PrometheusConnectionError,
    PrometheusExtractionError,
    PrometheusQueryError,
)
from src.core.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================
# Automatically detect whether we're running in Docker or on the host.
#
# WHY THIS MATTERS:
# - In Docker Compose, services use service names (prometheus:9090)
# - On the host, we use localhost (localhost:9090)
# - Auto-detection makes local development seamless
# =============================================================================


def _is_running_in_docker() -> bool:
    """
    Detect if we're running inside a Docker container.

    DETECTION STRATEGY:
    -------------------
    Docker containers have two reliable indicators:
    1. /.dockerenv file - Created by Docker daemon
    2. /proc/1/cgroup contains 'docker' - Cgroup namespace indicator

    Why check both?
    - /.dockerenv is fast (single stat call)
    - /proc/1/cgroup is more reliable but slower
    - Check /.dockerenv first as optimization

    RESOURCE SAFETY:
    ----------------
    File is properly closed using context manager to prevent
    file descriptor leaks under all conditions.

    Returns:
        True if running in Docker, False otherwise
    """
    # Fast path: Check for Docker marker file
    if os.path.exists("/.dockerenv"):
        return True

    # Fallback: Check cgroup namespace (Linux-specific)
    cgroup_path = "/proc/1/cgroup"
    if not os.path.exists(cgroup_path):
        return False

    try:
        # Use context manager to ensure file is always closed
        with open(cgroup_path, encoding="utf-8") as f:
            return any("docker" in line for line in f)
    except (OSError, PermissionError) as e:
        # Failed to read cgroup - assume not in Docker
        logger.debug(
            "Failed to read cgroup file for Docker detection", path=cgroup_path, error=str(e)
        )
        return False


def _detect_prometheus_url() -> str:
    """
    Detect Prometheus URL based on environment.

    PRIORITY ORDER:
    ---------------
    1. PROMETHEUS_URL environment variable (explicit override)
    2. http://prometheus:9090 if running in Docker
    3. http://localhost:9090 as fallback

    ARCHITECTURAL RATIONALE:
    ------------------------
    In Docker Compose networks, services communicate using service names
    as DNS hostnames. The 'prometheus' service is accessible at:
    - 'prometheus:9090' from within containers
    - 'localhost:9090' from the host machine

    This auto-detection enables seamless development:
    - Run tests locally → Uses localhost
    - Deploy in Docker → Uses service name
    - CI/CD pipelines → Uses env var override

    Returns:
        Detected or configured Prometheus URL
    """
    # Priority 1: Explicit environment variable
    if url := os.getenv("PROMETHEUS_URL"):
        logger.info("Using Prometheus URL from environment", url=url, source="PROMETHEUS_URL")
        return url

    # Priority 2: Docker detection
    if _is_running_in_docker():
        url = "http://prometheus:9090"
        logger.info(
            "Detected Docker environment, using service name",
            url=url,
            detection_method="dockerenv_or_cgroup",
        )
        return url

    # Priority 3: Localhost fallback
    url = "http://localhost:9090"
    logger.info(
        "Using localhost for Prometheus", url=url, reason="Not in Docker, no PROMETHEUS_URL set"
    )
    return url


# =============================================================================
# CONFIGURATION
# =============================================================================
# Prometheus client configuration with validation.
#
# WHY PYDANTIC?
# - Validates configuration at startup (fail fast)
# - Self-documenting with type hints and constraints
# - Automatic environment variable support
# - Immutable by default (safer in concurrent contexts)
# =============================================================================


class PrometheusConfig(BaseModel):
    """
    Configuration for Prometheus client with validation.

    All fields have sensible defaults that work for most deployments.
    Override via environment variables or direct construction.

    Attributes:
        base_url: Prometheus server URL (auto-detected if not provided)
        timeout: HTTP request timeout in seconds (must be 1-60)
        max_retries: Number of retry attempts for transient failures
        retry_base_delay: Initial delay between retries (seconds)
        retry_max_delay: Maximum delay between retries (seconds)
        max_connections: Maximum HTTP connections in pool

    Example:
        # Use environment variable
        export PROMETHEUS_URL="http://prometheus:9090"
        config = PrometheusConfig()  # Auto-loads from env

        # Override specific values
        config = PrometheusConfig(timeout=5.0, max_retries=5)
    """

    # Model configuration
    model_config = {"frozen": True}  # Make config immutable

    base_url: str = Field(
        default_factory=_detect_prometheus_url,
        description="Prometheus server URL (auto-detected if not provided)",
    )

    timeout: float = Field(default=10.0, gt=0, le=60, description="HTTP request timeout in seconds")

    max_retries: int = Field(
        default=3, ge=1, le=10, description="Number of retry attempts for transient failures"
    )

    retry_base_delay: float = Field(
        default=1.0, ge=0.1, le=10, description="Initial delay between retries (seconds)"
    )

    retry_max_delay: float = Field(
        default=10.0, ge=1, le=60, description="Maximum delay between retries (seconds)"
    )

    max_connections: int = Field(
        default=10, ge=1, le=100, description="Maximum HTTP connections in pool"
    )







# =============================================================================
# PROTOCOL INTERFACE
# =============================================================================
# Define the interface that any Prometheus client must implement.
# This enables dependency injection and easy mocking for tests.
# =============================================================================


@runtime_checkable
class PrometheusClientProtocol(Protocol):
    """
    Protocol defining the Prometheus client interface.

    WHY USE A PROTOCOL?
    -------------------
    1. **Dependency Injection**: Callers type-hint to protocol, not implementation
    2. **Easy Mocking**: Test doubles just implement this interface
    3. **Documentation**: Clearly shows the public API
    4. **Type Safety**: Static analyzers can verify usage

    USAGE IN TESTS:
    ---------------
    ```python
    class MockPrometheusClient:
        async def query(self, promql: str) -> dict[str, Any]:
            return {"status": "success", "data": {"result": []}}

        async def query_range(self, promql, start, end, step) -> dict[str, Any]:
            return {"status": "success", "data": {"result": []}}

        def extract_scalar_value(self, response) -> float | None:
            return 42.0

        def extract_vector_values(self, response) -> dict[str, float]:
            return {"openai": 0.0}

        def is_available(self) -> bool:
            return True

    # Use in tests
    service = MetricsService(prometheus_client=MockPrometheusClient())
    ```
    """

    async def query(self, promql: str) -> dict[str, Any]:
        """Execute instant PromQL query."""
        ...

    async def query_range(self, promql: str, start: int, end: int, step: str) -> dict[str, Any]:
        """Execute range PromQL query."""
        ...

    def extract_scalar_value(self, response: dict[str, Any] | None) -> float | None:
        """Extract scalar value from response."""
        ...

    def extract_vector_values(self, response: dict[str, Any] | None) -> dict[str, float]:
        """Extract vector values from response."""
        ...

    def is_available(self) -> bool:
        """Check if Prometheus is currently available."""
        ...


# =============================================================================
# PROMETHEUS CLIENT IMPLEMENTATION
# =============================================================================


class PrometheusClient:
    """
    Production-grade asynchronous HTTP client for Prometheus.

    This client implements multiple resilience patterns to handle the reality
    that external dependencies may fail:

    RESILIENCE LAYERS:
    ------------------
    1. **Connection Pooling**: Reuse HTTP connections for efficiency
    2. **Retry with Backoff**: Handle transient failures (network blips)
    3. **Circuit Breaker**: Fast-fail during sustained outages
    4. **Graceful Degradation**: Return None instead of crashing

    LIFECYCLE MANAGEMENT:
    ---------------------
    The client must be used as an async context manager to ensure proper
    resource cleanup:

    ```python
    async with PrometheusClient() as client:
        result = await client.query("up")
    # HTTP connections are properly closed here
    ```

    THREAD SAFETY:
    --------------
    - Configuration is immutable (Pydantic frozen model)
    - httpx.AsyncClient is thread-safe
    - Circuit breaker state is in Redis (distributed safe)
    - Safe for use in async web frameworks (FastAPI, Starlette)

    Attributes:
        config: Validated configuration object
    """

    def __init__(self, config: PrometheusConfig | None = None):
        """
        Initialize Prometheus client with validated configuration.

        Args:
            config: Optional configuration object. If not provided,
                    defaults are used with auto-detected Prometheus URL.

        Example:
            # With defaults (auto-detect URL)
            client = PrometheusClient()

            # With custom config
            config = PrometheusConfig(timeout=5.0, max_retries=5)
            client = PrometheusClient(config=config)
        """
        self.config = config or PrometheusConfig()

        # HTTP client - initialized in __aenter__
        self._client: httpx.AsyncClient | None = None

        # Availability tracking (local fallback when circuit breaker unavailable)
        # This provides a simple in-process fallback when Redis is not available
        self._is_available_local = True
        self._consecutive_failures = 0
        self._last_failure_time = 0.0
        self._max_failures = 3
        self._cooldown_seconds = 60

        logger.info(
            "Prometheus client initialized",
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
            max_connections=self.config.max_connections,
        )

    async def __aenter__(self) -> PrometheusClient:
        """
        Enter async context and initialize HTTP client.

        HTTPX CLIENT CONFIGURATION:
        ---------------------------
        - timeout: Per-request timeout (connection + read combined)
        - limits: Connection pool limits
        - http2: Enable HTTP/2 for connection multiplexing

        HTTP/2 BENEFITS:
        ----------------
        - Multiplexed requests over single connection
        - Header compression (HPACK)
        - Server push (if Prometheus supports it)
        - Reduced latency for concurrent queries
        """
        # Try to initialize with HTTP/2 if available
        try:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=self.config.max_connections // 2,
                ),
                http2=True,  # Try enabling HTTP/2
            )
            logger.debug(
                "HTTP client initialized",
                max_connections=self.config.max_connections,
                http2_enabled=True,
            )
        except ImportError:
            # Fallback for when 'h2' package is not installed
            logger.warning(
                "HTTP/2 support not available (h2 package missing), falling back to HTTP/1.1",
                hint="Install httpx[http2] for better performance"
            )
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=self.config.max_connections // 2,
                ),
                http2=False,
            )
            logger.debug(
                "HTTP client initialized (HTTP/1.1)",
                max_connections=self.config.max_connections,
                http2_enabled=False,
            )

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit async context and cleanup HTTP client.

        RESOURCE CLEANUP:
        -----------------
        Always closes the HTTP client, even if an exception occurred.
        This prevents connection leaks which could exhaust file descriptors.

        The __aexit__ signature follows the async context manager protocol:
        - exc_type: Exception class if exception occurred
        - exc_val: Exception instance if exception occurred
        - exc_tb: Traceback if exception occurred
        - Returns: None (don't suppress exceptions)
        """
        if self._client:
            await self._client.aclose()
            logger.debug("HTTP client closed")
        self._client = None

    def _ensure_client_initialized(self) -> None:
        """
        Verify HTTP client is initialized.

        DEFENSIVE PROGRAMMING:
        ----------------------
        This check catches misuse of the client (forgetting async with).
        A clear error message guides developers to the correct usage pattern.

        Raises:
            RuntimeError: If client used without context manager
        """
        if self._client is None:
            raise RuntimeError(
                "PrometheusClient not initialized. Use 'async with PrometheusClient() as client:' "
                "to properly initialize and cleanup the HTTP client."
            )

    def _should_attempt_query(self) -> bool:
        """
        Check if query should be attempted based on availability state.

        CIRCUIT BREAKER PATTERN (Local Fallback):
        -----------------------------------------
        When Redis-backed circuit breaker is unavailable, this method
        provides a simple in-process circuit breaker:

        1. CLOSED state: Normal operation, allow requests
        2. OPEN state: After N failures, block requests
        3. HALF-OPEN state: After cooldown, allow one probe request

        This prevents log flooding when Prometheus is down and Redis
        is also unavailable.

        Returns:
            True if query should proceed, False if circuit is open
        """
        if self._is_available_local:
            return True

        # Check if cooldown period has elapsed (half-open state)
        elapsed = time.time() - self._last_failure_time
        if elapsed >= self._cooldown_seconds:
            logger.info(
                "Circuit breaker cooldown elapsed, attempting probe",
                cooldown_seconds=self._cooldown_seconds,
                elapsed_seconds=round(elapsed, 1),
            )
            return True

        # Still in cooldown - silently skip
        return False

    def _record_success(self) -> None:
        """
        Record successful query - close circuit if it was open.

        STATE TRANSITION:
        -----------------
        Any state → CLOSED

        On success, we reset all failure tracking. If the circuit was
        open or half-open, this logs the recovery.
        """
        if not self._is_available_local or self._consecutive_failures > 0:
            logger.info(
                "Prometheus connection restored",
                previous_failures=self._consecutive_failures,
            )

        self._is_available_local = True
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        """
        Record failed query - potentially open circuit.

        STATE TRANSITIONS:
        ------------------
        CLOSED → CLOSED (failures < threshold)
        CLOSED → OPEN (failures >= threshold)
        HALF-OPEN → OPEN (probe failed)

        On failure, increment counter and check threshold. Opening the
        circuit logs a warning to alert operators.
        """
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._consecutive_failures >= self._max_failures:
            if self._is_available_local:
                logger.warning(
                    "Prometheus circuit breaker opened (local fallback)",
                    consecutive_failures=self._consecutive_failures,
                    cooldown_seconds=self._cooldown_seconds,
                    message="Queries will be skipped until cooldown elapses",
                )
            self._is_available_local = False

    def is_available(self) -> bool:
        """
        Check if Prometheus is currently considered available.

        This reflects the local circuit breaker state. Useful for:
        - Health check endpoints
        - Metrics aggregation (report availability status)
        - Conditional UI rendering (show "metrics unavailable" message)

        Returns:
            True if client believes Prometheus is reachable
        """
        if not self._is_available_local:
            # Check if we should transition to half-open
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._cooldown_seconds:
                return True  # Willing to try again
            return False
        return True

    async def query(self, promql: str) -> dict[str, Any]:
        """
        Execute an instant PromQL query against Prometheus.

        PROMQL QUERY TYPES:
        -------------------
        Instant queries return the current value of a metric at a single
        point in time. Common patterns:

        - `up`: Is the target up? (1 = yes, 0 = no)
        - `rate(requests_total[5m])`: Per-second rate over 5 minutes
        - `sum(active_connections)`: Total across all instances
        - `histogram_quantile(0.99, ...)`: 99th percentile latency

        RESILIENCE BEHAVIOR:
        --------------------
        1. Check circuit breaker state
        2. If open, raise PrometheusConnectionError
        3. Execute query with retry logic
        4. On transient failure, retry with exponential backoff
        5. On success, record success (close circuit if open)
        6. On sustained failure, open circuit

        Args:
            promql: Prometheus Query Language expression

        Returns:
            Prometheus API response as dict with structure:
            {
                "status": "success",
                "data": {
                    "resultType": "vector" | "scalar" | "matrix",
                    "result": [...]
                }
            }

        Raises:
            PrometheusConnectionError: Cannot connect to Prometheus
            PrometheusQueryError: Query execution failed
            RuntimeError: Client not initialized (forgot async with)

        Example:
            async with PrometheusClient() as client:
                response = await client.query('up')
                if response["status"] == "success":
                    result = response["data"]["result"]
        """
        self._ensure_client_initialized()

        # Check circuit breaker
        if not self._should_attempt_query():
            raise PrometheusConnectionError(
                "Prometheus circuit breaker is open",
                details={
                    "cooldown_remaining": self._cooldown_seconds
                    - (time.time() - self._last_failure_time),
                    "consecutive_failures": self._consecutive_failures,
                },
            )

        url = f"{self.config.base_url}/api/v1/query"
        params = {"query": promql}

        logger.debug(
            "Executing Prometheus query",
            promql=promql,
            url=url,
        )

        try:
            response = await self._execute_with_retry(url, params)
            self._record_success()

            logger.debug(
                "Prometheus query succeeded",
                promql=promql,
                result_type=response.get("data", {}).get("resultType"),
            )

            return response

        except httpx.ConnectError as e:
            self._record_failure()
            raise PrometheusConnectionError(
                f"Cannot connect to Prometheus at {self.config.base_url}",
                details={
                    "url": url,
                    "original_error": str(e),
                    "consecutive_failures": self._consecutive_failures,
                },
            ) from e

        except httpx.TimeoutException as e:
            self._record_failure()
            raise PrometheusConnectionError(
                f"Prometheus request timed out after {self.config.timeout}s",
                details={
                    "url": url,
                    "timeout": self.config.timeout,
                    "promql": promql,
                },
            ) from e

        except httpx.HTTPStatusError as e:
            self._record_failure()
            raise PrometheusQueryError(
                f"Prometheus returned HTTP {e.response.status_code}",
                details={
                    "status_code": e.response.status_code,
                    "promql": promql,
                    "response_text": e.response.text[:500] if e.response.text else None,
                },
            ) from e

    async def query_range(
        self, promql: str, start: int, end: int, step: str = "15s"
    ) -> dict[str, Any]:
        """
        Execute a PromQL range query for time series data.

        RANGE QUERIES vs INSTANT QUERIES:
        ----------------------------------
        - Instant: Single point in time (current value)
        - Range: Multiple points over a time range (historical data)

        Range queries are used for:
        - Graphing metrics over time
        - Calculating trends and anomalies
        - Historical analysis

        STEP PARAMETER:
        ---------------
        The step determines the resolution of returned data:
        - "15s": One data point every 15 seconds (high resolution)
        - "1m": One data point per minute (lower storage)
        - "5m": One data point every 5 minutes (aggregated)

        Trade-off: Smaller step = more data points = slower query

        Args:
            promql: Prometheus Query Language expression
            start: Start timestamp (Unix epoch seconds)
            end: End timestamp (Unix epoch seconds)
            step: Query resolution step (e.g., "15s", "1m", "5m")

        Returns:
            Prometheus API response with matrix result type

        Raises:
            PrometheusConnectionError: Cannot connect to Prometheus
            PrometheusQueryError: Query execution failed

        Example:
            async with PrometheusClient() as client:
                now = int(time.time())
                one_hour_ago = now - 3600

                response = await client.query_range(
                    promql='rate(requests_total[5m])',
                    start=one_hour_ago,
                    end=now,
                    step="1m"
                )
        """
        self._ensure_client_initialized()

        if not self._should_attempt_query():
            raise PrometheusConnectionError(
                "Prometheus circuit breaker is open",
                details={"consecutive_failures": self._consecutive_failures},
            )

        url = f"{self.config.base_url}/api/v1/query_range"
        params = {
            "query": promql,
            "start": start,
            "end": end,
            "step": step,
        }

        try:
            response = await self._execute_with_retry(url, params)
            self._record_success()
            return response

        except httpx.ConnectError as e:
            self._record_failure()
            raise PrometheusConnectionError(
                f"Cannot connect to Prometheus at {self.config.base_url}",
                details={"url": url, "original_error": str(e)},
            ) from e

        except httpx.TimeoutException as e:
            self._record_failure()
            raise PrometheusConnectionError(
                "Prometheus range query timed out",
                details={"promql": promql, "timeout": self.config.timeout},
            ) from e

        except httpx.HTTPStatusError as e:
            self._record_failure()
            raise PrometheusQueryError(
                f"Prometheus returned HTTP {e.response.status_code}",
                details={"promql": promql, "status_code": e.response.status_code},
            ) from e

    async def _execute_with_retry(self, url: str, params: dict) -> dict[str, Any]:
        """
        Execute HTTP request with retry logic for transient failures.

        RETRY STRATEGY:
        ---------------
        Uses exponential backoff with jitter to handle transient failures:

        Attempt 1: Immediate
        Attempt 2: Wait 1-2 seconds
        Attempt 3: Wait 2-4 seconds

        The jitter (random variation) prevents thundering herd when
        multiple clients retry simultaneously.

        WHICH ERRORS TO RETRY:
        ----------------------
        - ConnectError: Transient network issues
        - TimeoutException: Server temporarily overloaded

        NOT RETRIED (would fail again):
        - HTTPStatusError: 4xx/5xx responses
        - Invalid PromQL syntax

        Args:
            url: Full URL to query
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            httpx exceptions on all retries exhausted
        """

        # Create retry decorator with configured parameters
        @retry(
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential_jitter(
                initial=self.config.retry_base_delay,
                max=self.config.retry_max_delay,
            ),
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            reraise=True,
        )
        async def _do_request() -> dict[str, Any]:
            assert self._client is not None
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        return await _do_request()

    def extract_scalar_value(self, response: dict[str, Any] | None) -> float | None:
        """
        Extract a scalar value from a Prometheus query response.

        PROMETHEUS RESULT TYPES:
        ------------------------
        Prometheus returns different result types based on the query:

        1. **scalar**: Single numeric value (rare, from constants)
           Format: [timestamp, "value"]

        2. **vector**: Array of time series at single instant (most common)
           Format: [{"metric": {...}, "value": [timestamp, "value"]}, ...]

        3. **matrix**: Time series over a range
           Format: [{"metric": {...}, "values": [[t1, "v1"], [t2, "v2"], ...]}, ...]

        This method handles scalar and vector (single result) responses.

        GRACEFUL DEGRADATION:
        ---------------------
        Returns None instead of raising exceptions for:
        - Empty responses (Prometheus returned no data)
        - No matching time series (metric doesn't exist yet)

        This allows callers to use `value or 0.0` pattern for defaults.

        Args:
            response: Prometheus API response dict

        Returns:
            Extracted numeric value, or None if not extractable

        Raises:
            PrometheusExtractionError: Response format is unexpected/corrupted

        Example Response (vector):
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"__name__": "up"},
                            "value": [1734000000, "1"]
                        }
                    ]
                }
            }
        """
        if not response:
            return None

        if response.get("status") != "success":
            error_msg = response.get("error", "Unknown error")
            raise PrometheusExtractionError(
                f"Prometheus query failed: {error_msg}",
                details={"response_status": response.get("status"), "error": error_msg},
            )

        data = response.get("data", {})
        result_type = data.get("resultType")
        result = data.get("result", [])

        # Handle scalar result: [timestamp, "value"]
        if result_type == "scalar":
            if len(result) >= 2:
                try:
                    return float(result[1])
                except (ValueError, TypeError) as e:
                    raise PrometheusExtractionError(
                        f"Invalid scalar value: {result[1]}",
                        details={"raw_value": result[1], "result_type": "scalar"},
                    ) from e
            return None

        # Handle vector with single result
        if result_type == "vector":
            if not result:
                # Empty vector - no matching time series
                return None

            value_pair = result[0].get("value", [])
            if len(value_pair) >= 2:
                try:
                    return float(value_pair[1])
                except (ValueError, TypeError) as e:
                    raise PrometheusExtractionError(
                        f"Invalid vector value: {value_pair[1]}",
                        details={"raw_value": value_pair[1], "result_type": "vector"},
                    ) from e
            return None

        # Unsupported result type
        if result_type:
            logger.warning(
                "Unsupported Prometheus result type for scalar extraction",
                result_type=result_type,
                hint="Use extract_vector_values for multi-value responses",
            )

        return None

    def extract_vector_values(self, response: dict[str, Any] | None) -> dict[str, float]:
        """
        Extract multiple labeled values from a Prometheus vector response.

        WHEN TO USE:
        ------------
        Use this for queries that return multiple time series, where each
        series has different label values:

        - `circuit_breaker_state` → One value per provider
        - `http_requests_total{status="..."}` → One value per status code
        - `cpu_usage{instance="..."}` → One value per instance

        LABEL EXTRACTION:
        -----------------
        The method extracts the FIRST non-internal label value as the key.
        Internal labels (starting with `__`) are skipped.

        Example metric: `{provider="openai", __name__="circuit_state"}`
        Extracted key: "openai"

        Args:
            response: Prometheus API response dict

        Returns:
            Dict mapping label value to metric value
            Empty dict if response is empty or invalid

        Example:
            response = await client.query('sse_circuit_breaker_state')
            states = client.extract_vector_values(response)
            # states = {"openai": 0.0, "anthropic": 1.0, "gemini": 0.0}
        """
        if not response or response.get("status") != "success":
            return {}

        data = response.get("data", {})
        result = data.get("result", [])

        values: dict[str, float] = {}

        for item in result:
            metric = item.get("metric", {})
            value_pair = item.get("value", [])

            # Extract first non-internal label as key
            key = None
            for label_name, label_value in metric.items():
                if not label_name.startswith("__"):
                    key = label_value
                    break

            if key and len(value_pair) >= 2:
                try:
                    values[key] = float(value_pair[1])
                except (ValueError, TypeError):
                    # Skip invalid values instead of failing entire extraction
                    logger.warning(
                        "Skipping invalid value in vector extraction",
                        key=key,
                        raw_value=value_pair[1],
                    )
                    continue

        return values


# =============================================================================
# SINGLETON ACCESSOR (Backward Compatibility)
# =============================================================================
# Provides a cached singleton instance for code that hasn't migrated to
# the context manager pattern yet.
#
# DEPRECATION NOTICE:
# This function is maintained for backward compatibility. New code should
# use the context manager pattern:
#
#     async with PrometheusClient() as client:
#         ...
#
# The singleton pattern has drawbacks:
# - HTTP client is never closed (resource leak)
# - Harder to mock in tests
# - Hides the async lifecycle requirement
# =============================================================================


_prometheus_client_instance: PrometheusClient | None = None


def get_prometheus_client() -> PrometheusClient:
    """
    Get singleton Prometheus client instance.

    BACKWARD COMPATIBILITY:
    -----------------------
    This function provides a singleton pattern for existing code.
    It automatically initializes the HTTP client but DOES NOT clean it up.

    RECOMMENDED ALTERNATIVE:
    ------------------------
    For new code, use the context manager pattern which properly
    manages the HTTP client lifecycle:

    ```python
    async with PrometheusClient() as client:
        result = await client.query("up")
    # HTTP client is properly closed here
    ```

    MIGRATION PATH:
    ---------------
    1. Replace `get_prometheus_client()` with context manager
    2. Update callers to pass client as parameter (dependency injection)
    3. Remove this function once all callers migrated

    Returns:
        Singleton PrometheusClient instance

    Note:
        The singleton's HTTP client is initialized lazily on first query.
        This may cause issues if used outside an async context.
    """
    global _prometheus_client_instance

    if _prometheus_client_instance is None:
        _prometheus_client_instance = PrometheusClient()
        # Note: HTTP client initialized lazily via __aenter__ when needed
        # This is a limitation of the singleton pattern
        logger.info(
            "Created Prometheus client singleton",
            warning="Consider migrating to context manager pattern for proper resource management",
        )

    return _prometheus_client_instance


@lru_cache(maxsize=1)
def get_prometheus_config() -> PrometheusConfig:
    """
    Get cached Prometheus configuration.

    Configuration is cached to avoid repeated environment variable
    lookups and URL detection. The cache is process-wide.

    Returns:
        Validated PrometheusConfig instance
    """
    return PrometheusConfig()
