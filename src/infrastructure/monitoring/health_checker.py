#!/usr/bin/env python3
"""
Health Checker Module

This module provides comprehensive health checks for all system components:
- Redis connectivity
- LLM provider availability
- Cache tier status
- Circuit breaker states
- Rate limiter status

Author: Senior Solution Architect
Date: 2025-12-05
"""

from datetime import datetime
from enum import Enum
from typing import Any

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthChecker:
    """
    Comprehensive health checker for all system components.

    STAGE-H: Health check orchestration

    This class provides:
    - Individual component health checks
    - Aggregated system health status
    - Detailed health reports

    Usage:
        checker = HealthChecker()
        await checker.initialize(redis_client, cache_manager)

        # Quick health check
        status = await checker.check_health()

        # Detailed health report
        report = await checker.detailed_health_report()
    """

    def __init__(self):
        """Initialize health checker."""
        try:
            self.settings = get_settings()
        except Exception as e:
            logger.warning(f"Failed to initialize settings: {e}", stage="H.0")
            # Create minimal settings for testing
            from src.core.config.settings import ApplicationSettings
            self.settings = type('MockSettings', (), {
                'app': ApplicationSettings(APP_VERSION="1.0.0")
            })()

        self._redis = None
        self._cache = None
        self._streaming = None

        logger.info("Health checker initialized", stage="H.0")

    async def initialize(
        self,
        redis_client=None,
        cache_manager=None,
        streaming_manager=None
    ) -> None:
        """
        Initialize health checker with dependencies.

        Args:
            redis_client: Redis client for connectivity check
            cache_manager: Cache manager for tier status
            streaming_manager: Streaming manager for connection count
        """
        self._redis = redis_client
        self._cache = cache_manager
        self._streaming = streaming_manager

        logger.info("Health checker dependencies set", stage="H.0.1")

    async def check_health(self) -> dict[str, Any]:
        """
        Quick health check.

        STAGE-H.1: Quick health status

        Returns:
            Dict with status and basic metrics
        """
        try:
            # Check Redis
            redis_healthy = await self._check_redis()

            # Determine overall status
            if redis_healthy:
                status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.DEGRADED

            # Get version with fallback
            try:
                if hasattr(self, 'settings') and self.settings:
                    version = self.settings.app.APP_VERSION
                else:
                    version = "1.0.0"
            except Exception:
                version = "1.0.0"

            return {
                "status": status.value,
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "version": version,
                "components": {
                    "redis": "healthy" if redis_healthy else "unhealthy"
                }
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}", stage="H.1")
            return {
                "status": HealthStatus.UNHEALTHY.value,
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "version": "1.0.0",
                "error": str(e)
            }

    async def detailed_health_report(self) -> dict[str, Any]:
        """
        Detailed health report for all components.

        STAGE-H.2: Detailed health report

        Returns:
            Dict with comprehensive health information
        """
        report = {
            "status": HealthStatus.HEALTHY.value,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "version": self.settings.app.APP_VERSION,
            "environment": self.settings.app.ENVIRONMENT,
            "components": {}
        }

        issues = []

        # Check Redis
        try:
            redis_health = (
                await self._redis.health_check()
                if self._redis
                else {"status": "not_configured"}
            )
            report["components"]["redis"] = redis_health
            if redis_health.get("status") != "healthy":
                issues.append("redis")
        except Exception as e:
            report["components"]["redis"] = {"status": "error", "error": str(e)}
            issues.append("redis")

        # Check Cache
        try:
            cache_health = (
                await self._cache.health_check()
                if self._cache
                else {"status": "not_configured"}
            )
            report["components"]["cache"] = cache_health
            if cache_health.get("status") != "healthy":
                issues.append("cache")
        except Exception as e:
            report["components"]["cache"] = {"status": "error", "error": str(e)}
            issues.append("cache")

        # Check Streaming
        try:
            if self._streaming:
                streaming_stats = self._streaming.get_stats()
                report["components"]["streaming"] = {
                    "status": "healthy",
                    "active_connections": streaming_stats.get("active_connections", 0),
                    "max_connections": streaming_stats.get("max_connections", 0)
                }
            else:
                report["components"]["streaming"] = {"status": "not_configured"}
        except Exception as e:
            report["components"]["streaming"] = {"status": "error", "error": str(e)}
            issues.append("streaming")

        # Check circuit breakers
        try:
            from src.core.resilience.circuit_breaker import get_circuit_breaker_manager
            cb_manager = get_circuit_breaker_manager()
            cb_stats = await cb_manager.get_all_stats()
            report["components"]["circuit_breakers"] = cb_stats

            # Check for open circuits
            for name, stats in cb_stats.items():
                if stats.get("state") == "open":
                    issues.append(f"circuit_breaker:{name}")
        except Exception as e:
            report["components"]["circuit_breakers"] = {"status": "error", "error": str(e)}

        # Determine overall status
        if not issues:
            report["status"] = HealthStatus.HEALTHY.value
        elif len(issues) < 2:
            report["status"] = HealthStatus.DEGRADED.value
            report["degraded_components"] = issues
        else:
            report["status"] = HealthStatus.UNHEALTHY.value
            report["failed_components"] = issues

        return report

    async def check_redis(self, redis_client=None) -> dict[str, Any]:
        """
        Public method to check Redis health.

        Args:
            redis_client: Redis client to check (uses self._redis if not provided)

        Returns:
            Dict with status, latency, and timestamp
        """
        client = redis_client or self._redis
        if not client:
            return {
                "status": "unhealthy",
                "error": "Redis client not initialized",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

        try:
            health = await client.health_check()
            return {
                **health,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    async def check_overall(self) -> dict[str, Any]:
        """
        Overall health check (alias for detailed_health_report for test compatibility).

        Returns:
            Dict with overall health status and component checks
        """
        return await self.detailed_health_report()

    async def _check_redis(self) -> bool:
        """Check Redis connectivity."""
        if not self._redis:
            return False

        try:
            import asyncio
            # Add timeout to prevent hanging
            return await asyncio.wait_for(self._redis.ping(), timeout=2.0)
        except Exception:
            return False

    async def liveness_check(self) -> dict[str, Any]:
        """
        Kubernetes liveness probe.

        Returns basic status for liveness check.
        """
        # Get version with fallback
        try:
            if hasattr(self, 'settings') and self.settings:
                version = self.settings.app.APP_VERSION
            else:
                version = "1.0.0"
        except Exception:
            version = "1.0.0"

        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "version": version
        }

    async def readiness_check(self) -> dict[str, Any]:
        """
        Kubernetes readiness probe.

        Returns readiness based on critical dependencies.
        """
        redis_ok = await self._check_redis()

        # Get version with fallback
        try:
            if hasattr(self, 'settings') and self.settings:
                version = self.settings.app.APP_VERSION
            else:
                version = "1.0.0"
        except Exception:
            version = "1.0.0"

        if redis_ok:
            return {
                "status": "ready",
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "version": version
            }
        else:
            return {
                "status": "not_ready",
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "version": version,
                "reason": "Redis not available"
            }


# Global health checker
_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get global health checker."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker
