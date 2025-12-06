"""
Admin Routes

This module contains administrative and monitoring endpoints.
"""

from fastapi import APIRouter, Response

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
