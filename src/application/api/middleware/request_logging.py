"""
Request Logging Middleware - Educational Documentation
=======================================================

WHAT IS MIDDLEWARE?
-------------------
Middleware is code that runs BEFORE and AFTER each request is processed.
It sits between the client and your route handlers, allowing you to:

1. Inspect/modify incoming requests
2. Inspect/modify outgoing responses
3. Execute code before/after route handlers
4. Short-circuit requests (return early without calling the handler)

MIDDLEWARE EXECUTION ORDER:
---------------------------
Middleware is executed in the order it's added to the app:

Request Flow:
    Client → Middleware 1 (before) → Middleware 2 (before) → Route Handler

Response Flow:
    Route Handler → Middleware 2 (after) → Middleware 1 (after) → Client

FASTAPI MIDDLEWARE PATTERNS:
----------------------------
There are two ways to create middleware in FastAPI:

1. @app.middleware("http") decorator:
   - Simple function-based approach
   - Good for straightforward middleware
   - Used in this module

2. BaseHTTPMiddleware class:
   - Class-based approach
   - Good for complex middleware with state
   - More verbose but more flexible

This module implements request/response logging middleware for observability.
"""

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================
# Headers that contain sensitive information and should not be logged
# This prevents accidentally logging passwords, API keys, etc.

SENSITIVE_HEADERS = {
    "authorization",  # Bearer tokens, Basic auth
    "cookie",  # Session cookies
    "x-api-key",  # API keys
    "x-auth-token",  # Authentication tokens
}


# ============================================================================
# REQUEST LOGGING MIDDLEWARE
# ============================================================================


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.

    BASEHTTPMIDDLEWARE EXPLAINED:
    -----------------------------
    BaseHTTPMiddleware is a Starlette class that provides a convenient
    way to create middleware. It handles the low-level details of:
    - Request/response processing
    - Exception handling
    - Async context management

    You just need to implement the dispatch() method, which:
    - Receives the request
    - Calls the next middleware/handler
    - Receives the response
    - Can modify request/response or perform logging

    LOGGING STRATEGY:
    -----------------
    This middleware logs:
    - Request: method, path, query params, headers (sanitized)
    - Response: status code, duration
    - Errors: Full exception details

    It does NOT log:
    - Request/response bodies (too large, may contain sensitive data)
    - Sensitive headers (passwords, tokens, etc.)

    For body logging, use a separate middleware or route-specific logic.
    """

    def __init__(self, app, log_level: str = "INFO"):
        """
        Initialize the request logging middleware.

        Args:
            app: The ASGI application (FastAPI app)
            log_level: Minimum log level for request logs (DEBUG, INFO, WARNING, ERROR)
        """
        super().__init__(app)
        self.log_level = log_level.upper()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process each request and log details.

        MIDDLEWARE DISPATCH METHOD:
        ---------------------------
        This method is called for EVERY HTTP request. It:
        1. Receives the request object
        2. Can inspect/modify the request
        3. Calls call_next(request) to invoke the next middleware/handler
        4. Receives the response
        5. Can inspect/modify the response
        6. Returns the response

        ASYNC/AWAIT IN MIDDLEWARE:
        --------------------------
        The dispatch method is async because:
        - call_next() is async (it awaits the route handler)
        - We can perform async operations (database queries, etc.)
        - Non-blocking (doesn't tie up threads)

        TIMING REQUESTS:
        ----------------
        We use time.perf_counter() for high-precision timing:
        - More accurate than time.time()
        - Monotonic (not affected by system clock changes)
        - Perfect for measuring durations

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/handler

        Returns:
            Response: The HTTP response (possibly modified)
        """
        # Record start time for duration calculation
        start_time = time.perf_counter()

        # Extract request details for logging
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else None

        # Sanitize headers (remove sensitive information)
        # This prevents accidentally logging passwords, API keys, etc.
        sanitized_headers = self._sanitize_headers(dict(request.headers))

        # Log incoming request
        # Using structured logging (key=value pairs) for better searchability
        logger.info(
            f"Incoming request: {method} {path}",
            method=method,
            path=path,
            query_params=query_params,
            headers=sanitized_headers,
            client_host=request.client.host if request.client else None,
        )

        try:
            # Call the next middleware or route handler
            # This is where the actual request processing happens
            # AWAIT is necessary because call_next is async
            response = await call_next(request)

            # Calculate request duration
            duration = time.perf_counter() - start_time

            # Log successful response
            logger.info(
                f"Request completed: {method} {path}",
                method=method,
                path=path,
                status_code=response.status_code,
                duration_seconds=round(duration, 4),
            )

            return response

        except Exception as e:
            # Log errors that occur during request processing
            # This catches exceptions from route handlers and other middleware
            duration = time.perf_counter() - start_time

            logger.error(
                f"Request failed: {method} {path}",
                method=method,
                path=path,
                error=str(e),
                error_type=type(e).__name__,
                duration_seconds=round(duration, 4),
                exc_info=True,  # Include full stack trace
            )

            # Re-raise the exception so FastAPI's exception handlers can process it
            # If we don't re-raise, the error would be swallowed
            raise

    def _sanitize_headers(self, headers: dict) -> dict:
        """
        Remove sensitive information from headers before logging.

        SECURITY BEST PRACTICE:
        -----------------------
        Never log sensitive information like:
        - Passwords
        - API keys
        - Session tokens
        - Authorization headers

        This method replaces sensitive header values with "[REDACTED]"
        so we can see which headers were present without exposing secrets.

        Args:
            headers: Dictionary of HTTP headers

        Returns:
            dict: Sanitized headers with sensitive values redacted
        """
        sanitized = {}

        for key, value in headers.items():
            # Check if header name is in the sensitive list
            # Use lowercase for case-insensitive comparison
            if key.lower() in SENSITIVE_HEADERS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value

        return sanitized


# ============================================================================
# HELPER FUNCTION FOR APP REGISTRATION
# ============================================================================


def add_request_logging_middleware(app, log_level: str = "INFO"):
    """
    Add request logging middleware to the FastAPI application.

    MIDDLEWARE REGISTRATION:
    ------------------------
    This helper function makes it easy to add the middleware to your app:

        from src.application.api.middleware.request_logging import add_request_logging_middleware

        app = FastAPI()
        add_request_logging_middleware(app)

    MIDDLEWARE ORDER MATTERS:
    -------------------------
    Middleware is executed in the order it's added. For logging, you typically want:
    1. Request ID middleware (first, so all logs have request ID)
    2. Request logging middleware (second, to log the request with ID)
    3. Other middleware

    Args:
        app: FastAPI application instance
        log_level: Minimum log level for request logs
    """
    app.add_middleware(RequestLoggingMiddleware, log_level=log_level)
    logger.info("Request logging middleware registered", log_level=log_level)
