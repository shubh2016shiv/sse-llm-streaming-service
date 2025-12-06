"""
Health Check Routes - Educational Documentation
================================================

WHAT ARE HEALTH CHECKS?
-----------------------
Health checks are endpoints that report the status of your application and
its dependencies (database, cache, external services, etc.). They're essential for:

1. Load Balancers: Determine which instances can receive traffic
2. Monitoring Systems: Alert when services are unhealthy
3. Orchestration Platforms (Kubernetes): Decide when to restart containers
4. Debugging: Quick way to check if dependencies are working

KUBERNETES HEALTH PROBES:
--------------------------
Kubernetes uses two types of health probes:

1. LIVENESS PROBE:
   - Question: "Is the application running?"
   - If fails: Kubernetes RESTARTS the container
   - Use case: Detect deadlocks, infinite loops, crashes
   - Should be simple and fast (just check if app is alive)

2. READINESS PROBE:
   - Question: "Is the application ready to serve traffic?"
   - If fails: Kubernetes REMOVES from load balancer (but doesn't restart)
   - Use case: Check dependencies (DB, cache, external APIs)
   - Can be more complex (check all critical dependencies)

BEST PRACTICES:
---------------
- Keep liveness checks simple (avoid checking dependencies)
- Make readiness checks comprehensive (check all critical dependencies)
- Return appropriate HTTP status codes (200 = healthy, 503 = unhealthy)
- Include timestamps for debugging
- Provide detailed info in separate endpoint (not in liveness/readiness)

This module contains all health check and monitoring endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.infrastructure.monitoring.health_checker import get_health_checker

# ============================================================================
# ROUTER SETUP
# ============================================================================
# Create a router for health-related endpoints
# - prefix="/health": All routes start with /health
# - tags=["Health"]: Groups in API docs under "Health"

router = APIRouter(prefix="/health", tags=["Health"])


# ============================================================================
# RESPONSE MODELS
# ============================================================================
# PYDANTIC RESPONSE MODELS:
# -------------------------
# Defining response models with Pydantic provides:
# 1. Automatic validation of response data
# 2. Automatic JSON serialization
# 3. OpenAPI schema generation (shows in /docs)
# 4. Type hints for better IDE support
# 5. Documentation of response structure


class HealthResponse(BaseModel):
    """
    Standard health check response model.

    PYDANTIC FIELD TYPES:
    ---------------------
    - str: String field
    - dict | None: Optional dictionary (can be None)

    The '| None' syntax is Python 3.10+ union type syntax.
    It means the field can be either the specified type OR None.

    Fields without default values are required.
    Fields with '= None' are optional.
    """

    status: str  # Required: "healthy", "unhealthy", "degraded"
    timestamp: str  # Required: ISO 8601 timestamp
    components: dict | None = None  # Optional: Status of individual components


# ============================================================================
# HEALTH CHECK ENDPOINTS
# ============================================================================


@router.get("", response_model=HealthResponse)
async def health_check():
    """
    Quick health check endpoint for load balancers.

    FASTAPI RESPONSE MODEL:
    -----------------------
    The 'response_model' parameter tells FastAPI:
    1. What structure the response should have
    2. How to validate the response data
    3. How to serialize it to JSON
    4. What to show in the OpenAPI docs

    If the function returns data that doesn't match the model,
    FastAPI will raise a validation error (helps catch bugs).

    ASYNC VS SYNC HANDLERS:
    -----------------------
    This is an 'async def' function, which means:
    - It runs in the async event loop
    - It can use 'await' for async operations
    - Multiple requests can be handled concurrently
    - Non-blocking (doesn't tie up threads)

    When to use async:
    - When calling async functions (database, HTTP clients, etc.)
    - For I/O-bound operations
    - When you need high concurrency

    When to use sync (def):
    - For CPU-bound operations
    - When calling sync-only libraries
    - For simple operations with no I/O

    USE CASE:
    ---------
    This endpoint is designed for load balancer health checks.
    It should be:
    - Fast (< 100ms)
    - Simple (minimal logic)
    - Reliable (rarely fails)

    Load balancers typically call this every few seconds to determine
    if the instance should receive traffic.

    Returns:
        HealthResponse: Basic health status with timestamp

    HTTP Status Codes:
        200: Application is healthy
        500: Application is unhealthy (automatic if exception occurs)
    """
    health_checker = get_health_checker()
    return await health_checker.check_health()


@router.get("/detailed")
async def detailed_health():
    """
    Detailed health check endpoint for debugging and monitoring.

    NO RESPONSE MODEL:
    ------------------
    Notice this endpoint doesn't specify response_model.
    This means:
    - FastAPI will serialize whatever dict/object we return
    - No strict validation (more flexible)
    - OpenAPI docs will show generic response schema

    This is fine for admin/debugging endpoints where the structure
    might vary or be complex.

    USE CASE:
    ---------
    This endpoint provides comprehensive health information including:
    - Status of each dependency (Redis, cache, etc.)
    - Performance metrics
    - Error counts
    - Configuration info

    It's useful for:
    - Debugging issues
    - Monitoring dashboards
    - Alerting systems
    - Manual health verification

    This endpoint can be slower and more detailed than the basic
    health check since it's not called by load balancers.

    Returns:
        dict: Detailed health report with component statuses

    HTTP Status Codes:
        200: Always returns 200 (even if some components are unhealthy)
             The status is in the response body, not the HTTP code
    """
    health_checker = get_health_checker()
    return await health_checker.detailed_health_report()


@router.get("/live")
async def liveness_probe():
    """
    Kubernetes liveness probe endpoint.

    KUBERNETES LIVENESS PROBE:
    --------------------------
    This endpoint answers: "Is the application process running?"

    Kubernetes behavior:
    - Calls this endpoint periodically (e.g., every 10 seconds)
    - If it fails N times in a row (e.g., 3 failures)
    - Kubernetes KILLS and RESTARTS the container

    What to check:
    - Application is running (not deadlocked)
    - Event loop is responsive
    - NOT dependencies (that's for readiness probe)

    Keep it simple:
    - Should complete in < 1 second
    - Minimal logic (just prove the app is alive)
    - Don't check external dependencies

    Why separate from readiness?
    - If DB is down, we don't want to restart the app
    - We just want to stop sending traffic (readiness)
    - Only restart if the app itself is broken (liveness)

    Returns:
        dict: Simple liveness status

    HTTP Status Codes:
        200: Application is alive and responsive
        500: Application is deadlocked or crashed
    """
    health_checker = get_health_checker()
    return await health_checker.liveness_check()


@router.get("/ready")
async def readiness_probe():
    """
    Kubernetes readiness probe endpoint.

    KUBERNETES READINESS PROBE:
    ---------------------------
    This endpoint answers: "Is the application ready to serve traffic?"

    Kubernetes behavior:
    - Calls this endpoint periodically (e.g., every 5 seconds)
    - If it fails, Kubernetes REMOVES the pod from the service
    - Traffic stops flowing to this instance
    - The pod is NOT restarted (unlike liveness)
    - When it passes again, traffic resumes

    What to check:
    - Database connectivity
    - Cache availability
    - Required external services
    - Any critical dependencies

    This can be more complex than liveness:
    - Can take a few seconds
    - Should check all critical dependencies
    - Determines if the app can handle requests

    USE CASE EXAMPLE:
    -----------------
    Scenario: Redis cache is down
    - Liveness: PASS (app is running)
    - Readiness: FAIL (can't serve requests without cache)
    - Result: Kubernetes stops sending traffic, but doesn't restart
    - When Redis recovers: Readiness passes, traffic resumes

    HTTP STATUS CODE HANDLING:
    --------------------------
    Notice the HTTPException usage:
    - If unhealthy, we raise HTTPException with status_code=503
    - 503 = Service Unavailable (standard for "not ready")
    - Kubernetes sees 503 and removes pod from load balancer
    - The 'detail' field provides debugging information

    Returns:
        dict: Readiness status with component details

    Raises:
        HTTPException: 503 if not ready to serve traffic

    HTTP Status Codes:
        200: Ready to serve traffic (all dependencies healthy)
        503: Not ready (one or more critical dependencies unavailable)
    """
    health_checker = get_health_checker()
    result = await health_checker.readiness_check()

    # Check if the application is ready
    # If not, raise an HTTP 503 error
    # FASTAPI EXCEPTION HANDLING:
    # ---------------------------
    # HTTPException is a special FastAPI exception that:
    # 1. Sets the HTTP status code
    # 2. Returns the detail as JSON response body
    # 3. Stops execution (doesn't continue to return statement)
    # 4. Is automatically caught and formatted by FastAPI
    if result["status"] != "ready":
        raise HTTPException(
            status_code=503,  # Service Unavailable
            detail=result,  # Include full health report in error response
        )

    # If we reach here, the app is ready
    return result
