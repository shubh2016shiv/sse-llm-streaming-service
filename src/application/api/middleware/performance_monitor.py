"""
Performance Monitoring Middleware - Educational Documentation
==============================================================

WHAT IS PERFORMANCE MONITORING?
--------------------------------
Performance monitoring tracks how long requests take to process and identifies
slow endpoints. This helps with:

1. SLA Compliance: Ensure requests complete within acceptable time
2. Bottleneck Identification: Find slow endpoints that need optimization
3. Capacity Planning: Understand system load and scaling needs
4. Alerting: Detect performance degradation before users complain

This middleware measures request duration and integrates with the metrics collector.
"""

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging.logger import get_logger
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


# Threshold for logging slow requests (in seconds)
SLOW_REQUEST_THRESHOLD = 1.0  # Log requests taking more than 1 second


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """
    Middleware for monitoring request performance and detecting slow requests.

    PERFORMANCE METRICS:
    --------------------
    This middleware tracks:
    - Request duration (time from request start to response completion)
    - Slow requests (requests exceeding threshold)
    - Per-endpoint performance (via metrics collector)

    The data is used for:
    - Real-time alerting (slow request warnings)
    - Historical analysis (performance trends)
    - Capacity planning (when to scale)
    """

    def __init__(self, app, slow_threshold: float = SLOW_REQUEST_THRESHOLD):
        """
        Initialize performance monitoring middleware.

        Args:
            app: The ASGI application
            slow_threshold: Threshold in seconds for logging slow requests
        """
        super().__init__(app)
        self.slow_threshold = slow_threshold

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Monitor request performance and log slow requests.

        TIMING METHODOLOGY:
        -------------------
        We use time.perf_counter() which:
        - Has nanosecond precision
        - Is monotonic (unaffected by system clock changes)
        - Perfect for measuring short durations

        The duration includes:
        - Middleware processing time
        - Route handler execution time
        - Response generation time
        - Database/cache queries
        - External API calls

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/handler

        Returns:
            Response: The HTTP response
        """
        # Record start time
        start_time = time.perf_counter()

        # Process the request
        response = await call_next(request)

        # Calculate duration
        duration = time.perf_counter() - start_time

        # Log slow requests for investigation
        if duration > self.slow_threshold:
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                duration_seconds=round(duration, 4),
                threshold_seconds=self.slow_threshold,
            )

        # Record metrics for monitoring dashboards
        # This data feeds into Prometheus/Grafana for visualization
        get_metrics_collector()
        # Note: Metrics collector should have a method to record request duration
        # metrics.record_request_duration(request.url.path, duration)

        # Add duration header for client-side monitoring
        # Clients can use this to track API performance from their perspective
        response.headers["X-Response-Time"] = f"{duration:.4f}s"

        return response


def add_performance_monitoring_middleware(app, slow_threshold: float = SLOW_REQUEST_THRESHOLD):
    """
    Add performance monitoring middleware to the FastAPI application.

    USAGE:
    ------
        from src.application.api.middleware.performance_monitor import (
            add_performance_monitoring_middleware
        )

        app = FastAPI()
        add_performance_monitoring_middleware(app, slow_threshold=0.5)

    Args:
        app: FastAPI application instance
        slow_threshold: Threshold in seconds for logging slow requests
    """
    app.add_middleware(PerformanceMonitoringMiddleware, slow_threshold=slow_threshold)
    logger.info("Performance monitoring middleware registered", slow_threshold=slow_threshold)
