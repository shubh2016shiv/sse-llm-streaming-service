#!/usr/bin/env python3
"""
FastAPI Application Entry Point

This is the main entry point for the SSE Streaming Microservice.
It configures the FastAPI application, middleware, and routes.

Author: Senior Solution Architect
Date: 2025-12-05
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import route modules
from src.api import admin_router, health_router, streaming_router
from src.caching import close_cache, get_cache_manager, init_cache
from src.config.constants import HEADER_THREAD_ID
from src.config.settings import get_settings
from src.core.exceptions import RateLimitExceededError, SSEBaseException
from src.core.logging import clear_thread_id, get_logger, set_thread_id, setup_logging
from src.core.redis import close_redis, get_redis_client, init_redis
from src.llm_providers import get_circuit_breaker_manager
from src.monitoring import get_health_checker, get_metrics_collector
from src.rate_limiting import setup_rate_limiting
from src.streaming import close_stream_lifecycle, init_stream_lifecycle

logger = get_logger(__name__)


# ============================================================================
# Application Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle (startup and shutdown).
    """
    settings = get_settings()

    # Setup logging
    setup_logging(
        log_level=settings.logging.LOG_LEVEL,
        log_format=settings.logging.LOG_FORMAT
    )

    logger.info(
        "Starting SSE Streaming Microservice",
        environment=settings.app.ENVIRONMENT,
        version=settings.app.APP_VERSION
    )

    try:
        # Initialize Redis
        await init_redis()
        logger.info("Redis connected")

        # Initialize cache
        await init_cache()
        logger.info("Cache initialized")

        # Initialize streaming lifecycle
        await init_stream_lifecycle()
        logger.info("Streaming lifecycle ready")

        # Register LLM providers
        from src.config.provider_registration import register_providers
        register_providers()
        logger.info("LLM providers registered")

        # Initialize circuit breaker manager
        circuit_breaker_manager = get_circuit_breaker_manager()
        await circuit_breaker_manager.initialize(get_redis_client())
        logger.info("Circuit breaker manager ready")

        # Initialize health checker
        health_checker = get_health_checker()
        await health_checker.initialize(
            redis_client=get_redis_client(),
            cache_manager=get_cache_manager(),
            streaming_manager=None  # Deprecated dependency
        )
        logger.info("Health checker ready")

        logger.info("Application startup complete")

        yield

    finally:
        # Shutdown
        logger.info("Shutting down application")

        await close_stream_lifecycle()
        await close_cache()
        await close_redis()

        logger.info("Application shutdown complete")


# ============================================================================
# Application Factory
# ============================================================================

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured application instance
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app.APP_NAME,
        version=settings.app.APP_VERSION,
        description="Production-ready SSE streaming microservice for LLM outputs",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[HEADER_THREAD_ID]
    )

    # Rate limiting middleware
    setup_rate_limiting(app)

    # Register routers
    app.include_router(health_router)
    app.include_router(streaming_router)
    app.include_router(admin_router)

    return app


# Create application instance
app = create_app()


# ============================================================================
# Middleware
# ============================================================================

@app.middleware("http")
async def thread_id_middleware(request: Request, call_next):
    """
    Inject thread ID into all requests for correlation.
    """
    # Generate or get thread ID from header
    thread_id = request.headers.get(HEADER_THREAD_ID) or str(uuid.uuid4())

    # Set in context for logging
    set_thread_id(thread_id)

    try:
        # Process request
        response = await call_next(request)

        # Add thread ID to response headers
        response.headers[HEADER_THREAD_ID] = thread_id

        return response

    finally:
        clear_thread_id()


# ============================================================================
# Root Endpoint
# ============================================================================

@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information.
    """
    settings = get_settings()
    return {
        "name": settings.app.APP_NAME,
        "version": settings.app.APP_VERSION,
        "environment": settings.app.ENVIRONMENT,
        "docs": "/docs",
        "health": "/health"
    }


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(SSEBaseException)
async def sse_exception_handler(request: Request, exc: SSEBaseException):
    """Handle SSE-specific exceptions."""
    logger.error(
        f"SSE exception: {exc.message}",
        error_type=type(exc).__name__,
        thread_id=exc.thread_id
    )

    return JSONResponse(
        status_code=500,
        content=exc.to_dict(),
        headers={HEADER_THREAD_ID: exc.thread_id or ""}
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_handler(request: Request, exc: RateLimitExceededError):
    """Handle rate limit exceeded errors."""
    metrics = get_metrics_collector()
    metrics.record_rate_limit_exceeded("user")

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
            "retry_after": 60
        },
        headers={"Retry-After": "60"}
    )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app:app",
        host=settings.app.API_HOST,
        port=settings.app.API_PORT,
        reload=settings.app.ENVIRONMENT == "development",
        log_level=settings.logging.LOG_LEVEL.lower()
    )
