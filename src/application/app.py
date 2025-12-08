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
from src.application.api.routes.admin import router as admin_router
from src.application.api.routes.health import router as health_router
from src.application.api.routes.streaming import router as streaming_router
from src.core.config.constants import HEADER_THREAD_ID
from src.core.config.settings import get_settings
from src.core.exceptions import RateLimitExceededError, SSEBaseError
from src.core.logging.logger import clear_thread_id, get_logger, set_thread_id, setup_logging
from src.core.observability.execution_tracker import get_tracker
from src.core.resilience.circuit_breaker import get_circuit_breaker_manager
from src.core.resilience.rate_limiter import setup_rate_limiting
from src.infrastructure.cache.cache_manager import close_cache, get_cache_manager, init_cache
from src.infrastructure.cache.redis_client import close_redis, get_redis_client, init_redis
from src.infrastructure.monitoring.health_checker import get_health_checker
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector

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
    setup_logging(log_level=settings.logging.LOG_LEVEL, log_format=settings.logging.LOG_FORMAT)

    logger.info(
        "Starting SSE Streaming Microservice",
        environment=settings.app.ENVIRONMENT,
        version=settings.app.APP_VERSION,
    )

    try:
        # Initialize Redis
        await init_redis()
        logger.info("Redis connected")

        # Initialize cache
        await init_cache()
        cache_manager = get_cache_manager()
        logger.info("Cache initialized")

        # Initialize global components for DI
        tracker = get_tracker()

        # Initialize provider factory and register providers
        from src.llm_stream.providers.base_provider import ProviderFactory

        provider_factory = ProviderFactory()

        # Register LLM providers
        from src.core.config.provider_registry import register_providers

        register_providers(provider_factory)
        logger.info("LLM providers registered")

        # Initialize Stream Orchestrator with dependencies
        from src.llm_stream.services.stream_orchestrator import StreamOrchestrator

        orchestrator = StreamOrchestrator(
            cache_manager=cache_manager,
            provider_factory=provider_factory,
            execution_tracker=tracker,
            settings=settings,
        )

        # Store in app state for dependencies.py
        app.state.orchestrator = orchestrator
        logger.info("Stream Orchestrator ready")

        # Initialize circuit breaker manager
        circuit_breaker_manager = get_circuit_breaker_manager()
        await circuit_breaker_manager.initialize(get_redis_client())
        logger.info("Circuit breaker manager ready")

        # Initialize health checker
        health_checker = get_health_checker()
        await health_checker.initialize(
            redis_client=get_redis_client(),
            cache_manager=cache_manager,
            streaming_manager=orchestrator,
        )
        logger.info("Health checker ready")

        logger.info("Application startup complete")

        yield

    finally:
        # Shutdown
        logger.info("Shutting down application")

        # Cleanup
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
        redoc_url="/redoc",
    )

    # ========================================================================
    # MIDDLEWARE REGISTRATION
    # ========================================================================
    # ENTERPRISE DECISION: Middleware Order Matters
    # ----------------------------------------------
    # Middleware is executed in REVERSE order of registration (last added = first executed).
    # Our order ensures:
    # 1. Errors are caught first (ErrorHandlingMiddleware)
    # 2. CORS headers are added to all responses (including errors)
    # 3. Rate limiting happens after error handling
    #
    # This prevents scenarios like:
    # - Rate limit errors not having CORS headers
    # - Unhandled exceptions bypassing error formatting

    # 1. Error handling middleware (catches all unhandled exceptions)
    # ENTERPRISE BEST PRACTICE: Centralized error handling ensures:
    # - Consistent error response format across all endpoints
    # - Security: prevents stack trace leakage in production
    # - Observability: all errors are logged in one place
    from src.application.api.middleware.error_handler import ErrorHandlingMiddleware

    app.add_middleware(
        ErrorHandlingMiddleware,
        include_traceback=(settings.app.ENVIRONMENT == "development")
    )

    # 2. CORS middleware (adds CORS headers to all responses)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[HEADER_THREAD_ID],
    )

    # 3. Rate limiting middleware (protects against abuse)
    setup_rate_limiting(app)

    # ========================================================================
    # ROUTER REGISTRATION
    # ========================================================================
    # ENTERPRISE DECISION: Configurable Base URL
    # -------------------------------------------
    # All API endpoints are prefixed with API_BASE_PATH (default: /api/v1)
    # This provides:
    # - Professional API versioning (/api/v1, /api/v2, etc.)
    # - Easy version management without code changes
    # - Clear separation from root endpoints (/, /docs, /redoc)
    # - Industry-standard URL structure
    #
    # Configuration:
    # - Set API_BASE_PATH in .env or settings
    # - Use empty string ("") for root-level endpoints
    # - Individual routes maintain their semantic paths (/stream, /health, /admin)
    #
    # Example URLs:
    # - POST /api/v1/stream (streaming endpoint)
    # - GET /api/v1/health (health check)
    # - GET /api/v1/admin/metrics (metrics endpoint)

    base_path = settings.API_BASE_PATH

    # Register routers with base path prefix
    app.include_router(health_router, prefix=base_path)
    app.include_router(streaming_router, prefix=base_path)
    app.include_router(admin_router, prefix=base_path)

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
        "health": "/health",
    }


# ============================================================================
# Exception Handlers
# ============================================================================


@app.exception_handler(SSEBaseError)
async def sse_exception_handler(request: Request, exc: SSEBaseError):
    """Handle SSE-specific exceptions."""
    logger.error(
        f"SSE exception: {exc.message}", error_type=type(exc).__name__, thread_id=exc.thread_id
    )

    return JSONResponse(
        status_code=500, content=exc.to_dict(), headers={HEADER_THREAD_ID: exc.thread_id or ""}
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
            "retry_after": 60,
        },
        headers={"Retry-After": "60"},
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
        log_level=settings.logging.LOG_LEVEL.lower(),
    )
