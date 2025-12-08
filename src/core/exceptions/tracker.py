"""
Execution Tracker Exceptions

All exceptions related to execution tracking operations

Author: System Architect
Date: 2025-12-08
"""

from src.core.exceptions.base import SSEBaseError


class ExecutionTrackerError(SSEBaseError):
    """Base exception for execution tracker errors."""
    pass


class StageNotFoundError(ExecutionTrackerError):
    """
    Raised when stage is not found in execution tracker.

    Common causes:
    - Invalid stage ID
    - Stage not tracked (sampling disabled)
    - Thread data cleared prematurely
    - Wrong thread ID
    """
    pass
