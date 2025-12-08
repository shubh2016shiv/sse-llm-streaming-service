"""
Streaming Exceptions

All exceptions related to SSE streaming operations

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class StreamingError(SSEBaseError):
    """Base exception for streaming errors."""
    pass


class StreamingTimeoutError(StreamingError):
    """
    Raised when streaming operation times out.

    Common causes:
    - First chunk timeout exceeded
    - Total request timeout exceeded
    - Idle connection timeout
    - Provider stopped responding
    """
    pass


class ConnectionPoolExhaustedError(StreamingError):
    """
    Raised when connection pool is exhausted.

    This indicates the system is at maximum capacity and cannot
    accept new streaming connections.

    Common causes:
    - Too many concurrent connections
    - Connections not being released
    - Connection leak
    - Insufficient pool size
    """
    pass
