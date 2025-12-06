"""
API Package

This package contains the API routes for the SSE streaming microservice.
"""

from .admin_routes import router as admin_router
from .health_routes import router as health_router
from .streaming_routes import router as streaming_router

__all__ = [
    "health_router",
    "streaming_router",
    "admin_router",
]
