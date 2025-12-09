"""
Connection Pool Manager for SSE Streaming Connections.

This module provides centralized connection pool management with:
- Distributed coordination via Redis
- Connection limits enforcement
- Per-user connection limits
- Health state monitoring
- Graceful backpressure
- Comprehensive stage-based logging

STAGE-CP: Connection Pool Management
-------------------------------------
CP.1: Connection acquisition
CP.2: Connection validation
CP.3: Connection tracking
CP.4: Connection release
CP.5: Health monitoring

Author: System Architect
Date: 2025-12-09
"""

import asyncio
from enum import Enum

from src.core.config.constants import (
    CONNECTION_POOL_CRITICAL_THRESHOLD,
    CONNECTION_POOL_DEGRADED_THRESHOLD,
    MAX_CONCURRENT_CONNECTIONS,
    MAX_CONNECTIONS_PER_USER,
)
from src.core.exceptions.connection_pool import (
    ConnectionPoolError,
    ConnectionPoolExhaustedError,
    UserConnectionLimitError,
)
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class ConnectionState(str, Enum):
    """Connection pool health states."""

    HEALTHY = "healthy"          # < 70% capacity
    DEGRADED = "degraded"        # 70-90% capacity
    CRITICAL = "critical"        # 90-100% capacity
    EXHAUSTED = "exhausted"      # At 100% capacity


class ConnectionPoolManager:
    """
    Centralized connection pool manager for SSE streaming.

    STAGE-CP.0: Connection Pool Manager Initialization

    This manager provides:
    - Atomic connection allocation/release
    - Distributed tracking via Redis
    - Per-user connection limits
    - Health state monitoring
    - Graceful degradation

    Architecture:
    - Redis-backed for multi-instance coordination
    - Local fallback if Redis unavailable
    - Thread-safe with async locks
    """

    def __init__(
        self,
        max_connections: int = MAX_CONCURRENT_CONNECTIONS,
        max_per_user: int = MAX_CONNECTIONS_PER_USER,
        redis_client=None
    ):
        """
        Initialize connection pool manager.

        Args:
            max_connections: Maximum total concurrent connections
            max_per_user: Maximum connections per user
            redis_client: Redis client for distributed coordination
        """
        self.max_connections = max_connections
        self.max_per_user = max_per_user
        self._redis = redis_client

        # Local counters (fallback when Redis unavailable)
        self._local_total_count = 0
        self._local_user_counts: dict[str, int] = {}
        self._local_connections: set[str] = set()

        # Thread safety
        self._lock = asyncio.Lock()

        # Redis keys
        self._key_total = "connection_pool:total"
        self._key_user_prefix = "connection_pool:user:"
        self._key_connections = "connection_pool:connections"

        # Thresholds for health states
        self._degraded_threshold = int(max_connections * CONNECTION_POOL_DEGRADED_THRESHOLD)
        self._critical_threshold = int(max_connections * CONNECTION_POOL_CRITICAL_THRESHOLD)

        logger.info(
            "Connection pool manager initialized",
            stage="CP.0",
            max_connections=max_connections,
            max_per_user=max_per_user,
            degraded_threshold=self._degraded_threshold,
            critical_threshold=self._critical_threshold,
            redis_enabled=redis_client is not None
        )

    async def acquire_connection(self, user_id: str, thread_id: str) -> bool:
        """
        Attempt to acquire a connection slot.

        STAGE-CP.1: Connection Acquisition

        This performs:
        1. Atomic check of total connections
        2. Check per-user connection limit
        3. Reserve connection slot
        4. Update tracking

        Args:
            user_id: User identifier
            thread_id: Thread/request identifier

        Returns:
            bool: True if connection acquired successfully

        Raises:
            ConnectionPoolExhaustedError: If pool is at capacity
            UserConnectionLimitError: If user exceeds per-user limit
        """
        async with self._lock:
            logger.info(
                "Attempting to acquire connection",
                stage="CP.1",
                user_id=user_id,
                thread_id=thread_id
            )

            try:
                # Get current counts
                total_count = await self._get_total_count()
                user_count = await self._get_user_count(user_id)

                logger.debug(
                    "Current connection counts",
                    stage="CP.1.1",
                    thread_id=thread_id,
                    total_count=total_count,
                    user_count=user_count,
                    max_total=self.max_connections,
                    max_per_user=self.max_per_user
                )

                # Check total capacity
                if total_count >= self.max_connections:
                    logger.error(
                        "Connection pool exhausted",
                        stage="CP.1.2",
                        thread_id=thread_id,
                        total_count=total_count,
                        max_connections=self.max_connections
                    )
                    raise ConnectionPoolExhaustedError(
                        details={
                            "current": total_count,
                            "max": self.max_connections,
                            "user_id": user_id
                        }
                    )

                # Check per-user limit
                if user_count >= self.max_per_user:
                    logger.warning(
                        "User connection limit exceeded",
                        stage="CP.1.3",
                        thread_id=thread_id,
                        user_id=user_id,
                        user_count=user_count,
                        max_per_user=self.max_per_user
                    )
                    raise UserConnectionLimitError(
                        user_id=user_id,
                        limit=self.max_per_user,
                        details={"current": user_count}
                    )

                # Reserve connection
                await self._increment_counts(user_id, thread_id)

                # Log successful acquisition
                new_total = total_count + 1
                utilization = (new_total / self.max_connections) * 100
                state = await self.get_pool_state()

                logger.info(
                    "Connection acquired from pool "
                    f"(utilization: {utilization:.1f}%, state: {state})",
                    stage="CP.1.4",
                    thread_id=thread_id,
                    user_id=user_id,
                    total_connections=new_total,
                    user_connections=user_count + 1,
                    utilization_percent=utilization,
                    pool_state=state
                )

                return True

            except (ConnectionPoolExhaustedError, UserConnectionLimitError):
                # Re-raise connection pool errors
                raise
            except Exception as e:
                logger.error(
                    f"Unexpected error acquiring connection: {str(e)}",
                    stage="CP.1.ERROR",
                    thread_id=thread_id,
                    error=str(e)
                )
                raise ConnectionPoolError(
                    message=f"Failed to acquire connection: {str(e)}",
                    details={"thread_id": thread_id, "error": str(e)}
                )

    async def release_connection(self, thread_id: str, user_id: str | None = None) -> None:
        """
        Release a connection slot back to the pool.

        STAGE-CP.4: Connection Release

        Args:
            thread_id: Thread/request identifier
            user_id: User identifier (optional, for user count tracking)
        """
        async with self._lock:
            try:
                logger.info(
                    "Releasing connection",
                    stage="CP.4",
                    thread_id=thread_id,
                    user_id=user_id
                )

                # Decrement counts
                await self._decrement_counts(user_id, thread_id)

                # Log successful release
                total_count = await self._get_total_count()
                utilization = (total_count / self.max_connections) * 100
                state = await self.get_pool_state()

                logger.info(
                    f"Connection released (utilization: {utilization:.1f}%, state: {state})",
                    stage="CP.4.1",
                    thread_id=thread_id,
                    total_connections=total_count,
                    utilization_percent=utilization,
                    pool_state=state
                )

            except Exception as e:
                logger.error(
                    f"Error releasing connection: {str(e)}",
                    stage="CP.4.ERROR",
                    thread_id=thread_id,
                    error=str(e)
                )

    async def get_pool_state(self) -> ConnectionState:
        """
        Get current pool health state.

        STAGE-CP.5: Health Monitoring

        Returns:
            ConnectionState: Current pool state
        """
        try:
            total_count = await self._get_total_count()

            if total_count >= self.max_connections:
                return ConnectionState.EXHAUSTED
            elif total_count >= self._critical_threshold:
                return ConnectionState.CRITICAL
            elif total_count >= self._degraded_threshold:
                return ConnectionState.DEGRADED
            else:
                return ConnectionState.HEALTHY

        except Exception as e:
            logger.error(
                f"Error getting pool state: {str(e)}",
                stage="CP.5.ERROR",
                error=str(e)
            )
            return ConnectionState.HEALTHY  # Fail open

    async def get_stats(self) -> dict:
        """
        Get detailed pool statistics.

        Returns:
            dict: Pool statistics including counts, utilization, and state
        """
        try:
            total_count = await self._get_total_count()
            utilization = (
                (total_count / self.max_connections) * 100
                if self.max_connections > 0 else 0
            )
            state = await self.get_pool_state()

            return {
                "total_connections": total_count,
                "max_connections": self.max_connections,
                "utilization_percent": round(utilization, 2),
                "state": state.value,
                "degraded_threshold": self._degraded_threshold,
                "critical_threshold": self._critical_threshold,
                "redis_enabled": self._redis is not None
            }
        except Exception as e:
            logger.error(f"Error getting pool stats: {str(e)}", error=str(e))
            return {
                "error": str(e),
                "total_connections": 0,
                "max_connections": self.max_connections
            }

    # =========================================================================
    # Internal Methods - Redis + Local Fallback
    # =========================================================================

    async def _get_total_count(self) -> int:
        """Get total connection count from Redis or local fallback."""
        if self._redis:
            try:
                count = await self._redis.get(self._key_total)
                return int(count) if count else 0
            except Exception:
                pass
        return self._local_total_count

    async def _get_user_count(self, user_id: str) -> int:
        """Get user connection count from Redis or local fallback."""
        if self._redis:
            try:
                count = await self._redis.get(f"{self._key_user_prefix}{user_id}")
                return int(count) if count else 0
            except Exception:
                pass
        return self._local_user_counts.get(user_id, 0)

    async def _increment_counts(self, user_id: str, thread_id: str) -> None:
        """Increment connection counts atomically."""
        if self._redis:
            try:
                await self._redis.incr(self._key_total)
                await self._redis.incr(f"{self._key_user_prefix}{user_id}")
                await self._redis.sadd(self._key_connections, thread_id)
                return
            except Exception as e:
                logger.warning(
                    f"Redis increment failed, using local fallback: {str(e)}",
                    stage="CP.3.FALLBACK"
                )

        # Local fallback
        self._local_total_count += 1
        self._local_user_counts[user_id] = self._local_user_counts.get(user_id, 0) + 1
        self._local_connections.add(thread_id)

    async def _decrement_counts(self, user_id: str | None, thread_id: str) -> None:
        """Decrement connection counts atomically."""
        if self._redis:
            try:
                await self._redis.decr(self._key_total)
                if user_id:
                    count = await self._redis.decr(f"{self._key_user_prefix}{user_id}")
                    # Clean up if user has no more connections
                    if int(count) if count else 0 <= 0:
                        await self._redis.delete(f"{self._key_user_prefix}{user_id}")
                await self._redis.srem(self._key_connections, thread_id)
                return
            except Exception as e:
                logger.warning(
                    f"Redis decrement failed, using local fallback: {str(e)}",
                    stage="CP.4.FALLBACK"
                )

        # Local fallback
        self._local_total_count = max(0, self._local_total_count - 1)
        if user_id and user_id in self._local_user_counts:
            self._local_user_counts[user_id] = max(0, self._local_user_counts[user_id] - 1)
            if self._local_user_counts[user_id] == 0:
                del self._local_user_counts[user_id]
        self._local_connections.discard(thread_id)


# Global instance
_connection_pool_manager: ConnectionPoolManager | None = None


def get_connection_pool_manager() -> ConnectionPoolManager:
    """
    Get the global connection pool manager instance.

    Returns:
        ConnectionPoolManager: Global instance
    """
    global _connection_pool_manager

    if _connection_pool_manager is None:
        _connection_pool_manager = ConnectionPoolManager()

    return _connection_pool_manager


def initialize_connection_pool_manager(
    max_connections: int = MAX_CONCURRENT_CONNECTIONS,
    redis_client=None
) -> ConnectionPoolManager:
    """
    Initialize the global connection pool manager.

    Args:
        max_connections: Maximum concurrent connections
        redis_client: Redis client for distributed coordination

    Returns:
        ConnectionPoolManager: Initialized instance
    """
    global _connection_pool_manager

    _connection_pool_manager = ConnectionPoolManager(
        max_connections=max_connections,
        redis_client=redis_client
    )

    return _connection_pool_manager
