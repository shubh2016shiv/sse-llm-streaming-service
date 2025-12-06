"""
Error Handling Middleware - Educational Documentation
======================================================

WHAT IS CENTRALIZED ERROR HANDLING?
------------------------------------
Centralized error handling provides a consistent way to handle exceptions
across your entire application. Instead of try/except in every route handler,
middleware catches all exceptions and formats them consistently.

BENEFITS:
---------
1. Consistency: All errors have the same format
2. Security: Hide internal details from clients
3. Logging: Centralized error logging
4. Monitoring: Track error rates and types
5. DRY: Don't repeat error handling code

FASTAPI ERROR HANDLING:
-----------------------
FastAPI provides multiple error handling mechanisms:

1. Exception handlers (@app.exception_handler)
2. Middleware (this approach)
3. Route-level try/except

This middleware complements FastAPI's exception handlers by providing
a catch-all for unexpected errors.
"""

import traceback
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging.logger import get_logger
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

logger = get_logger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for centralized error handling and formatting.

    ERROR HANDLING STRATEGY:
    ------------------------
    This middleware catches ALL exceptions that aren't handled by:
    - Route handlers
    - Other middleware
    - FastAPI exception handlers

    It provides a last line of defense to ensure:
    - No unhandled exceptions crash the server
    - All errors are logged
    - Clients get meaningful error responses
    - Internal details aren't exposed
    """

    def __init__(self, app, include_traceback: bool = False):
        """
        Initialize error handling middleware.

        Args:
            app: The ASGI application
            include_traceback: Whether to include stack traces in error responses
                              (should be False in production for security)
        """
        super().__init__(app)
        self.include_traceback = include_traceback

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Catch and handle all exceptions during request processing.

        EXCEPTION HANDLING FLOW:
        ------------------------
        1. Try to process the request normally
        2. If exception occurs:
           a. Log the error with full context
           b. Record error metrics
           c. Format a user-friendly error response
           d. Return error response (don't crash)

        SECURITY CONSIDERATION:
        -----------------------
        We don't expose internal error details to clients because:
        - Stack traces reveal code structure
        - Error messages might contain sensitive data
        - Attackers can use error info to find vulnerabilities

        Instead, we:
        - Log full details server-side
        - Return generic error message to client
        - Include error ID for correlation

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/handler

        Returns:
            Response: Either normal response or formatted error response
        """
        try:
            # Try to process the request normally
            response = await call_next(request)
            return response

        except Exception as e:
            # An unhandled exception occurred
            # This is our last chance to handle it gracefully

            # Extract request details for logging
            method = request.method
            path = request.url.path
            error_type = type(e).__name__
            error_message = str(e)

            # Log the error with full context
            # exc_info=True includes the full stack trace in logs
            logger.error(
                f"Unhandled exception in request: {method} {path}",
                method=method,
                path=path,
                error_type=error_type,
                error_message=error_message,
                exc_info=True,  # Include stack trace in logs
            )

            # Record error metrics for monitoring
            metrics = get_metrics_collector()
            metrics.record_error(error_type, "unhandled_exception")

            # Build error response
            error_response = {
                "error": "internal_server_error",
                "message": "An unexpected error occurred while processing your request",
                "error_type": error_type,  # Include error type for debugging
            }

            # Include stack trace in development (not production!)
            # This helps with debugging but exposes internal details
            if self.include_traceback:
                error_response["traceback"] = traceback.format_exc()
                error_response["detail"] = error_message

            # Return formatted error response
            # Status code 500 = Internal Server Error
            return JSONResponse(status_code=500, content=error_response)


def add_error_handling_middleware(app, include_traceback: bool = False):
    """
    Add error handling middleware to the FastAPI application.

    USAGE:
    ------
        from src.application.api.middleware.error_handler import add_error_handling_middleware
        from src.core.config.settings import get_settings

        app = FastAPI()
        settings = get_settings()

        # Include tracebacks in development, not in production
        add_error_handling_middleware(
            app,
            include_traceback=(settings.app.ENVIRONMENT == "development")
        )

    MIDDLEWARE ORDER:
    -----------------
    Error handling middleware should be added EARLY in the middleware chain
    so it can catch errors from other middleware and route handlers.

    Recommended order:
    1. Error handling (this) - catch all errors
    2. Request logging - log requests/responses
    3. Security headers - add security headers
    4. Other middleware

    Args:
        app: FastAPI application instance
        include_traceback: Whether to include stack traces in responses
    """
    app.add_middleware(ErrorHandlingMiddleware, include_traceback=include_traceback)
    logger.info("Error handling middleware registered", include_traceback=include_traceback)
