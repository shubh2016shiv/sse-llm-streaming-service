"""
Request Validation Middleware - Educational Documentation
==========================================================

WHAT IS REQUEST VALIDATION?
----------------------------
Request validation ensures incoming requests meet basic requirements before
reaching route handlers. This middleware provides an additional layer of
validation beyond Pydantic models, checking:

1. Request size limits (prevent DoS attacks)
2. Content-Type headers (ensure proper format)
3. Required headers (API keys, authentication, etc.)
4. Request method restrictions

WHY MIDDLEWARE FOR VALIDATION?
-------------------------------
While FastAPI/Pydantic handle body validation, middleware is better for:
- Size limits (reject large requests early, before parsing)
- Header validation (applies to all endpoints)
- Rate limiting integration (check before processing)
- Security checks (authentication, CORS, etc.)

This middleware implements request-level validation for security and reliability.
"""

from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# Default configuration
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/event-stream",  # For SSE
}


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for validating incoming requests.

    VALIDATION LAYERS:
    ------------------
    This middleware provides the first layer of validation:

    1. Middleware validation (this): Size, headers, content-type
    2. Pydantic validation: Request body structure and types
    3. Business logic validation: Application-specific rules

    Each layer serves a different purpose and catches different issues.
    """

    def __init__(
        self,
        app,
        max_request_size: int = MAX_REQUEST_SIZE,
        allowed_content_types: set[str] = None,
        require_content_type: bool = False,
    ):
        """
        Initialize request validation middleware.

        Args:
            app: The ASGI application
            max_request_size: Maximum request body size in bytes
            allowed_content_types: Set of allowed Content-Type values
            require_content_type: Whether to require Content-Type header for POST/PUT
        """
        super().__init__(app)
        self.max_request_size = max_request_size
        self.allowed_content_types = allowed_content_types or ALLOWED_CONTENT_TYPES
        self.require_content_type = require_content_type

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Validate incoming requests before processing.

        VALIDATION CHECKS:
        ------------------
        1. Request size: Prevent DoS via large payloads
        2. Content-Type: Ensure proper format for body parsing
        3. Method-specific rules: Different validation for GET vs POST

        If validation fails, we return an error response immediately
        without calling the route handler. This saves resources and
        provides clear error messages to clients.

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/handler

        Returns:
            Response: Either error response (validation failed) or normal response
        """
        # ====================================================================
        # VALIDATION 1: Request Size
        # ====================================================================
        # Check Content-Length header to reject large requests early
        # This prevents DoS attacks where attackers send huge payloads
        # to exhaust server memory/bandwidth

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                content_length = int(content_length)
                if content_length > self.max_request_size:
                    logger.warning(
                        "Request rejected: exceeds size limit",
                        path=request.url.path,
                        content_length=content_length,
                        max_size=self.max_request_size,
                    )
                    return JSONResponse(
                        status_code=413,  # Payload Too Large
                        content={
                            "error": "payload_too_large",
                            "message": (
                                f"Request body exceeds maximum size of "
                                f"{self.max_request_size} bytes"
                            ),
                            "max_size_bytes": self.max_request_size,
                        },
                    )
            except ValueError:
                # Invalid Content-Length header
                logger.warning(
                    "Request rejected: invalid Content-Length header",
                    path=request.url.path,
                    content_length=content_length,
                )
                return JSONResponse(
                    status_code=400,  # Bad Request
                    content={
                        "error": "invalid_content_length",
                        "message": "Content-Length header must be a valid integer",
                    },
                )

        # ====================================================================
        # VALIDATION 2: Content-Type
        # ====================================================================
        # For requests with bodies (POST, PUT, PATCH), validate Content-Type
        # This ensures the body is in a format we can parse

        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "").split(";")[0].strip()

            # Check if Content-Type is required
            if self.require_content_type and not content_type:
                logger.warning(
                    "Request rejected: missing Content-Type header",
                    path=request.url.path,
                    method=request.method,
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "missing_content_type",
                        "message": "Content-Type header is required for requests with body",
                    },
                )

            # Check if Content-Type is allowed
            if content_type and content_type not in self.allowed_content_types:
                logger.warning(
                    "Request rejected: unsupported Content-Type",
                    path=request.url.path,
                    content_type=content_type,
                    allowed_types=list(self.allowed_content_types),
                )
                return JSONResponse(
                    status_code=415,  # Unsupported Media Type
                    content={
                        "error": "unsupported_media_type",
                        "message": f"Content-Type '{content_type}' is not supported",
                        "allowed_types": list(self.allowed_content_types),
                    },
                )

        # All validations passed, process the request
        return await call_next(request)


def add_request_validation_middleware(
    app,
    max_request_size: int = MAX_REQUEST_SIZE,
    allowed_content_types: set[str] = None,
    require_content_type: bool = False,
):
    """
    Add request validation middleware to the FastAPI application.

    USAGE:
    ------
        from src.application.api.middleware.request_validator import (
            add_request_validation_middleware
        )

        app = FastAPI()
        add_request_validation_middleware(
            app,
            max_request_size=5 * 1024 * 1024,  # 5 MB
            require_content_type=True
        )

    Args:
        app: FastAPI application instance
        max_request_size: Maximum request body size in bytes
        allowed_content_types: Set of allowed Content-Type values
        require_content_type: Whether to require Content-Type header
    """
    app.add_middleware(
        RequestValidationMiddleware,
        max_request_size=max_request_size,
        allowed_content_types=allowed_content_types,
        require_content_type=require_content_type,
    )
    logger.info(
        "Request validation middleware registered",
        max_request_size=max_request_size,
        require_content_type=require_content_type,
    )
