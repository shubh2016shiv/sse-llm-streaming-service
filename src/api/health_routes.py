"""
Health Check Routes

This module contains all health check and monitoring endpoints.
"""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.monitoring import get_health_checker

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: str
    components: dict | None = None


@router.get("", response_model=HealthResponse)
async def health_check():
    """
    Quick health check endpoint.

    Returns basic health status for load balancer checks.
    """
    health_checker = get_health_checker()
    return await health_checker.check_health()


@router.get("/detailed")
async def detailed_health():
    """
    Detailed health check endpoint.

    Returns comprehensive health information for debugging.
    """
    health_checker = get_health_checker()
    return await health_checker.detailed_health_report()


@router.get("/live")
async def liveness_probe():
    """
    Kubernetes liveness probe.

    Indicates if the application is running.
    """
    health_checker = get_health_checker()
    return await health_checker.liveness_check()


@router.get("/ready")
async def readiness_probe():
    """
    Kubernetes readiness probe.

    Indicates if the application is ready to accept traffic.
    """
    health_checker = get_health_checker()
    result = await health_checker.readiness_check()

    if result["status"] != "ready":
        raise HTTPException(status_code=503, detail=result)

    return result
