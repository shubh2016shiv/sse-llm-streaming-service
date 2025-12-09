"""
Connection Pool Exception Types.

Custom exceptions for connection pool management errors.
"""

from src.core.exceptions.base import SSEBaseError


class ConnectionPoolError(SSEBaseError):
    """Base exception for connection pool errors."""

    def __init__(
        self,
        message: str = "Connection pool error",
        code: str = "CONNECTION_POOL_ERROR",
        details: dict | None = None
    ):
        super().__init__(message=message, code=code, details=details)


class ConnectionPoolExhaustedError(ConnectionPoolError):
    """Raised when connection pool is at capacity."""

    def __init__(self, message: str | None = None, details: dict | None = None):
        super().__init__(
            message=message or "Connection pool exhausted - server at capacity",
            code="CONNECTION_POOL_EXHAUSTED",
            details=details
        )


class UserConnectionLimitError(ConnectionPoolError):
    """Raised when user exceeds per-user connection limit."""

    def __init__(self, user_id: str, limit: int, details: dict | None = None):
        super().__init__(
            message=f"User {user_id} exceeded connection limit ({limit})",
            code="USER_CONNECTION_LIMIT_EXCEEDED",
            details=details or {"user_id": user_id, "limit": limit}
        )
