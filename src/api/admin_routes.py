"""
Admin Routes

This module contains administrative and monitoring endpoints.
"""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.core.execution_tracker import get_tracker
from src.llm_providers import get_circuit_breaker_manager
from src.monitoring import get_metrics_collector

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/execution-stats")
async def get_execution_statistics():
    """
    Get execution statistics by stage.

    Returns performance statistics for each processing stage.
    """
    tracker = get_tracker()

    stages = ["1", "2", "2.1", "2.2", "3", "4", "5", "6"]
    stats = {}

    for stage in stages:
        stats[stage] = tracker.get_stage_statistics(stage)

    return stats


@router.get("/circuit-breakers")
async def get_circuit_breaker_statistics():
    """
    Get circuit breaker statistics.

    Returns state and statistics for all circuit breakers.
    """
    circuit_breaker_manager = get_circuit_breaker_manager()
    return circuit_breaker_manager.get_all_stats()


@router.get("/metrics")
async def get_prometheus_metrics():
    """
    Get Prometheus metrics.

    Returns metrics in Prometheus text format for scraping.
    """
    metrics_collector = get_metrics_collector()
    return Response(
        content=metrics_collector.get_prometheus_metrics(),
        media_type=metrics_collector.get_content_type()
    )


class UpdateConfigRequest(BaseModel):
    USE_FAKE_LLM: bool | None = None
    ENABLE_CACHING: bool | None = None
    QUEUE_TYPE: str | None = None

@router.post("/config")
async def update_configuration(request: UpdateConfigRequest):
    """
    Update feature flags for experiments.
    """
    from src.config.settings import get_settings
    settings = get_settings()

    if request.USE_FAKE_LLM is not None:
        settings.USE_FAKE_LLM = request.USE_FAKE_LLM
        # Re-register providers if fake LLM changed
        from src.config.provider_registration import register_providers
        register_providers()

    if request.ENABLE_CACHING is not None:
        settings.ENABLE_CACHING = request.ENABLE_CACHING

    if request.QUEUE_TYPE is not None:
        settings.QUEUE_TYPE = request.QUEUE_TYPE

    return {
        "status": "updated",
        "current_config": {
            "USE_FAKE_LLM": settings.USE_FAKE_LLM,
            "ENABLE_CACHING": settings.ENABLE_CACHING,
            "QUEUE_TYPE": settings.QUEUE_TYPE
        }
    }

@router.get("/config")
async def get_configuration():
    """
    Get current feature flags.
    """
    from src.config.settings import get_settings
    settings = get_settings()

    return {
        "USE_FAKE_LLM": settings.USE_FAKE_LLM,
        "ENABLE_CACHING": settings.ENABLE_CACHING,
        "QUEUE_TYPE": settings.QUEUE_TYPE
    }
