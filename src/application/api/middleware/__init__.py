"""
Middleware Package - Educational Documentation
===============================================

WHAT IS THIS PACKAGE?
---------------------
This package contains all middleware components for the FastAPI application.
Middleware sits between the client and route handlers, processing requests
and responses.

AVAILABLE MIDDLEWARE:
---------------------
1. request_logging: Log all requests and responses
2. security_headers: Add security headers to responses
3. performance_monitor: Track request duration and detect slow requests
4. request_validator: Validate request size and content-type
5. error_handler: Centralized error handling and formatting

MIDDLEWARE ORDERING:
--------------------
The order in which middleware is added matters! Middleware executes in order
for requests and in reverse order for responses:

Request flow:  Client → MW1 → MW2 → MW3 → Handler
Response flow: Handler → MW3 → MW2 → MW1 → Client

RECOMMENDED ORDER:
------------------
1. Error handling (catch all errors from other middleware)
2. Request logging (log all requests, even those that error)
3. Performance monitoring (measure total request time)
4. Security headers (add to all responses)
5. Request validation (validate before processing)
6. Application-specific middleware

USAGE EXAMPLE:
--------------
    from fastapi import FastAPI
    from src.application.api.middleware import setup_middleware

    app = FastAPI()
    setup_middleware(app)

This module provides a convenient function to register all middleware in the correct order.
"""

from fastapi import FastAPI

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger

from .error_handler import add_error_handling_middleware
from .performance_monitor import add_performance_monitoring_middleware
from .request_logging import add_request_logging_middleware
from .request_validator import add_request_validation_middleware
from .security_headers import add_security_headers_middleware

logger = get_logger(__name__)


def setup_middleware(app: FastAPI):
    """
    Register all middleware components in the correct order.

    MIDDLEWARE REGISTRATION ORDER:
    ------------------------------
    This function registers middleware in the optimal order for:
    - Security (error handling first, security headers early)
    - Observability (logging and monitoring)
    - Performance (validation before heavy processing)

    The order is carefully chosen to ensure:
    1. All errors are caught and logged
    2. All responses have security headers
    3. Performance is accurately measured
    4. Invalid requests are rejected early

    WHY A SETUP FUNCTION?
    ---------------------
    Instead of manually adding middleware in app.py, we use this function to:
    - Centralize middleware configuration
    - Ensure correct ordering
    - Make it easy to enable/disable middleware
    - Provide a single place for middleware documentation

    CUSTOMIZATION:
    --------------
    To customize middleware behavior, modify the settings or pass custom configs:

        from src.application.api.middleware import setup_middleware
        from src.application.api.middleware.security_headers import SecurityHeadersConfig

        app = FastAPI()

        # Option 1: Use default configuration
        setup_middleware(app)

        # Option 2: Custom configuration (modify this function)
        # Add parameters to this function for custom configs

    Args:
        app: FastAPI application instance
    """
    settings = get_settings()

    logger.info("Registering middleware components...")

    # ========================================================================
    # 1. ERROR HANDLING MIDDLEWARE (First - catches all errors)
    # ========================================================================
    # This MUST be first so it can catch errors from all other middleware
    # and route handlers. It provides a safety net for unhandled exceptions.
    #
    # Include tracebacks in development for debugging, but not in production
    # for security (don't expose internal details to clients).
    add_error_handling_middleware(
        app, include_traceback=(settings.app.ENVIRONMENT == "development")
    )

    # ========================================================================
    # 2. REQUEST LOGGING MIDDLEWARE (Second - logs everything)
    # ========================================================================
    # This should be early so it logs all requests, including those that
    # fail in other middleware or route handlers.
    #
    # It logs after error handling so errors are properly caught and logged.
    add_request_logging_middleware(app, log_level="INFO")

    # ========================================================================
    # 3. PERFORMANCE MONITORING MIDDLEWARE (Third - measures total time)
    # ========================================================================
    # This should be early to measure the total request processing time,
    # including all middleware and route handler execution.
    #
    # Slow request threshold: 1 second (log requests taking longer)
    add_performance_monitoring_middleware(app, slow_threshold=1.0)

    # ========================================================================
    # 4. SECURITY HEADERS MIDDLEWARE (Fourth - adds headers to all responses)
    # ========================================================================
    # This adds security headers to all responses, protecting against
    # common web vulnerabilities (XSS, clickjacking, etc.).
    #
    # It's placed here so headers are added even if errors occur in
    # later middleware or route handlers.
    add_security_headers_middleware(app)

    # ========================================================================
    # 5. REQUEST VALIDATION MIDDLEWARE (Fifth - validates before processing)
    # ========================================================================
    # This validates requests early to reject invalid requests before
    # they reach route handlers, saving resources.
    #
    # It's placed after logging/monitoring so we can track rejected requests.
    add_request_validation_middleware(
        app,
        max_request_size=10 * 1024 * 1024,  # 10 MB limit
        require_content_type=False,  # Don't require Content-Type (FastAPI handles this)
    )

    logger.info("All middleware components registered successfully")


# Export middleware components for direct use if needed
__all__ = [
    "setup_middleware",
    "add_error_handling_middleware",
    "add_request_logging_middleware",
    "add_performance_monitoring_middleware",
    "add_security_headers_middleware",
    "add_request_validation_middleware",
]
