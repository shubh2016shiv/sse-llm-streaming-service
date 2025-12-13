"""
Message Queue Base Module - Import Alias

This module provides an import alias for backward compatibility.
The actual MessageQueue interface is defined in src.core.interfaces.message_queue.

This file exists to support existing imports in:
- src.core.resilience.queue_consumer_worker.py
- src.core.resilience.queue_request_handler.py
"""

from src.core.interfaces.message_queue import MessageQueue, QueueMessage

__all__ = [
    "MessageQueue",
    "QueueMessage",
]
