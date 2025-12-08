"""
Message Queue Exceptions

All exceptions related to message queue operations (Redis Queue, Kafka, etc.)

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class QueueError(SSEBaseError):
    """Base exception for message queue errors."""
    pass


class QueueFullError(QueueError):
    """
    Raised when queue is full (backpressure).

    This indicates the system is under heavy load and cannot accept more messages.
    Clients should implement exponential backoff and retry.
    """
    pass


class QueueConsumerError(QueueError):
    """
    Raised when queue consumer encounters an error.

    Common causes:
    - Message deserialization failure
    - Consumer processing error
    - Connection to queue lost
    """
    pass
