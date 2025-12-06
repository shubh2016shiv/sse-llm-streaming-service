"""
FastAPI Dependency Injection Module - Educational Documentation
================================================================

WHAT IS DEPENDENCY INJECTION?
-----------------------------
Dependency Injection (DI) is a design pattern where objects receive their dependencies
from external sources rather than creating them internally. This makes code more:
- Testable (you can inject mock dependencies)
- Maintainable (dependencies are explicit and centralized)
- Flexible (easy to swap implementations)

FASTAPI'S DEPENDENCY INJECTION SYSTEM
--------------------------------------
FastAPI has a powerful built-in DI system that automatically:
1. Resolves dependencies before calling your route handler
2. Caches dependency results within a single request (by default)
3. Validates dependency outputs using type hints
4. Handles async and sync dependencies seamlessly
5. Supports dependency hierarchies (dependencies can have dependencies)

HOW IT WORKS - THE REQUEST LIFECYCLE:
--------------------------------------
When a request comes in to a route that uses dependencies:

1. FastAPI inspects the route function signature
2. It finds all parameters with `Depends()` annotations
3. It calls each dependency function in order
4. It passes the results to your route handler
5. Your route handler executes with all dependencies available

Example:
    @router.get("/example")
    async def my_route(settings: SettingsDep):
        # FastAPI automatically:
        # 1. Called get_settings()
        # 2. Validated the return type is Settings
        # 3. Passed the result as 'settings' parameter
        return {"env": settings.app.ENVIRONMENT}

This module defines reusable dependencies for accessing application singletons
(orchestrator, cache, settings, etc.) that are initialized during startup.
"""

from typing import Annotated

from fastapi import Depends, Request

from src.core.config.settings import Settings, get_settings
from src.core.observability.execution_tracker import ExecutionTracker, get_tracker
from src.llm_stream.services.stream_orchestrator import StreamOrchestrator

# ============================================================================
# DEPENDENCY FUNCTIONS
# ============================================================================
# These functions are called by FastAPI's DI system to provide dependencies
# to route handlers. They follow the "dependency provider" pattern.


def get_orchestrator(request: Request) -> StreamOrchestrator:
    """
    Retrieve the StreamOrchestrator singleton from application state.

    FASTAPI CONCEPT: Request Object
    --------------------------------
    The `Request` object is a special FastAPI dependency that gives you access to:
    - request.app: The FastAPI application instance
    - request.app.state: A namespace for storing application-level state
    - request.headers: HTTP headers
    - request.client: Client connection info
    - request.url: Request URL details

    WHY USE app.state?
    ------------------
    FastAPI's `app.state` is a simple namespace object where you can store
    application-level singletons that are initialized once during startup
    (in the lifespan context manager) and shared across all requests.

    This is better than global variables because:
    - It's explicitly tied to the app instance (better for testing)
    - It's initialized in the lifespan manager (proper lifecycle)
    - It's accessible from any request via the Request object

    SINGLETON PATTERN:
    ------------------
    The orchestrator is created ONCE during app startup and stored in app.state.
    Every request gets the SAME instance, which is efficient and maintains state.

    Args:
        request: FastAPI Request object (automatically injected by FastAPI)

    Returns:
        StreamOrchestrator: The global orchestrator instance

    Raises:
        RuntimeError: If orchestrator wasn't initialized during startup

    Example Usage in a Route:
        @router.post("/stream")
        async def stream_endpoint(orchestrator: OrchestratorDep):
            # orchestrator is automatically injected here
            async for event in orchestrator.stream(request):
                yield event
    """
    # Check if the orchestrator was initialized during app startup
    if not hasattr(request.app.state, "orchestrator"):
        # This should never happen in production if lifespan is properly configured
        # It might happen in tests if app.state isn't properly mocked
        raise RuntimeError(
            "StreamOrchestrator not initialized in app.state. "
            "This indicates the application lifespan startup didn't complete properly."
        )

    # Return the singleton instance
    return request.app.state.orchestrator


def get_execution_tracker() -> ExecutionTracker:
    """
    Retrieve the ExecutionTracker singleton.

    STATELESS SINGLETON PATTERN:
    ----------------------------
    Unlike the orchestrator, the ExecutionTracker doesn't need to be stored
    in app.state because it's a stateless singleton managed by a factory function.

    The get_tracker() function implements the singleton pattern internally,
    ensuring the same instance is returned every time it's called.

    WHY NO Request PARAMETER?
    --------------------------
    This dependency doesn't need the Request object because it doesn't access
    any request-specific data. It just returns a global singleton.

    FastAPI is smart enough to call this function without any arguments
    when it sees it used as a dependency.

    Returns:
        ExecutionTracker: The global execution tracker instance

    Example Usage:
        @router.get("/stats")
        async def get_stats(tracker: TrackerDep):
            return tracker.get_stage_statistics("1")
    """
    return get_tracker()


# ============================================================================
# TYPE ALIASES FOR CLEANER ROUTE SIGNATURES
# ============================================================================
# These use Python's `Annotated` type to combine type hints with FastAPI's
# `Depends()` marker, creating reusable dependency annotations.

# WHAT IS Annotated?
# ------------------
# Annotated[Type, metadata] is a Python 3.9+ feature that lets you attach
# metadata to type hints without changing the actual type.
#
# Example:
#   age: Annotated[int, "must be positive"]
#   The type is still 'int', but we've attached extra information.

# HOW FASTAPI USES Annotated:
# ----------------------------
# FastAPI looks for `Depends()` in the Annotated metadata and uses it to
# know that this parameter should be resolved via dependency injection.
#
# These two are equivalent:
#   def route1(settings: Annotated[Settings, Depends(get_settings)]): ...
#   def route1(settings: Settings = Depends(get_settings)): ...
#
# The Annotated version is preferred because:
# 1. Type checkers (mypy, pyright) understand it better
# 2. It separates the type from the dependency mechanism
# 3. It's more explicit about what's happening

# DEPENDENCY: StreamOrchestrator
# -------------------------------
# Use this in route signatures to get the orchestrator instance.
# FastAPI will automatically call get_orchestrator(request) and inject the result.
OrchestratorDep = Annotated[StreamOrchestrator, Depends(get_orchestrator)]

# DEPENDENCY: Settings
# --------------------
# Use this to get application settings/configuration.
# The get_settings() function is typically cached to return the same instance.
SettingsDep = Annotated[Settings, Depends(get_settings)]

# DEPENDENCY: ExecutionTracker
# ----------------------------
# Use this to get the execution tracker for performance monitoring.
TrackerDep = Annotated[ExecutionTracker, Depends(get_execution_tracker)]

# USAGE EXAMPLE:
# --------------
# Instead of writing:
#   async def my_route(
#       orchestrator: StreamOrchestrator = Depends(get_orchestrator),
#       settings: Settings = Depends(get_settings)
#   ):
#
# You can write:
#   async def my_route(
#       orchestrator: OrchestratorDep,
#       settings: SettingsDep
#   ):
#
# This is cleaner, more maintainable, and type-checker friendly!

# ADVANCED: Dependency Caching
# -----------------------------
# By default, FastAPI caches dependency results within a single request.
# If multiple route handlers or sub-dependencies use the same dependency,
# FastAPI calls the dependency function only ONCE per request.
#
# To disable caching, use: Depends(get_settings, use_cache=False)
#
# In our case, caching is beneficial because:
# - get_settings() returns the same config for the entire request
# - get_orchestrator() should return the same singleton
# - get_execution_tracker() returns the same singleton
