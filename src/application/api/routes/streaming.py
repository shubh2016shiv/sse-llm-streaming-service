"""
Streaming Routes - Educational Documentation
=============================================

FASTAPI CONCEPT: APIRouter
---------------------------
An APIRouter is a way to organize your routes into logical modules. Instead of
defining all routes on the main FastAPI app, you create routers for different
features (streaming, health, admin) and include them in the main app.

Benefits:
- Better code organization (separation of concerns)
- Reusable route modules
- Easier testing (can test routers independently)
- Cleaner main app file

How it works:
1. Create a router with APIRouter()
2. Define routes using @router.get(), @router.post(), etc.
3. Include the router in the main app: app.include_router(router)

The router can have a prefix (all routes start with this path) and tags
(for grouping in API documentation).

WHAT IS SSE (Server-Sent Events)?
----------------------------------
SSE is a web standard for pushing real-time updates from server to client
over HTTP. Unlike WebSockets (bidirectional), SSE is unidirectional (server → client).

SSE Protocol Format:
    event: message
    data: {"content": "Hello"}
    id: 123

    (blank line signals end of event)

Why SSE for LLM Streaming?
- Simple HTTP-based protocol (works through firewalls/proxies)
- Automatic reconnection built into browser EventSource API
- Perfect for one-way data flow (LLM → User)
- Lower overhead than WebSockets for this use case

ARCHITECTURE:
-------------
This module follows the Routes → Services → Models pattern:
- Route: HTTP handling only (this file)
- Service: Business logic (streaming_service.py)
- Models: Pydantic validation (models/streaming.py)

This separation reduces cognitive load and improves testability.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from src.application.api.dependencies import OrchestratorDep, UserIdDep
from src.application.api.models.streaming import (
    StreamRequestModel,
)
from src.application.services.streaming_service import get_streaming_service
from src.core.config.constants import HEADER_THREAD_ID

# ============================================================================
# ROUTER SETUP
# ============================================================================
# Create a router for all streaming-related endpoints.
# - prefix="/stream": All routes in this router will start with /stream
# - tags=["Streaming"]: Groups these endpoints in the API docs under "Streaming"

router = APIRouter(prefix="/stream", tags=["Streaming"])
logger = structlog.get_logger(__name__)


# ============================================================================
# AUTHENTICATION PLACEHOLDER
# ============================================================================
# TODO: Implement authentication in the future
# For now, this is a placeholder that always succeeds
# When ready to add auth, replace this with actual token verification


async def verify_stream_access() -> None:
    """
    Placeholder for streaming endpoint authentication.

    FUTURE IMPLEMENTATION:
    ----------------------
    When ready to add authentication:
    1. Add HTTPBearer dependency to extract token
    2. Verify JWT or API key
    3. Check user rate limits
    4. Raise HTTPException(401) if unauthorized

    Example:
        from fastapi.security import HTTPBearer

        security = HTTPBearer()

        async def verify_stream_access(
            credentials: HTTPAuthorizationCredentials = Depends(security)
        ) -> None:
            if not is_valid_token(credentials.credentials):
                raise HTTPException(status_code=401, detail="Invalid token")
    """
    pass  # No-op for now


# ============================================================================
# STREAMING ENDPOINT
# ============================================================================


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_stream_access)],
    responses={
        200: {
            "description": "SSE stream started successfully",
            "content": {"text/event-stream": {}},
        },
        422: {"description": "Validation error - invalid request format"},
        503: {"description": "Service unavailable - all resilience layers exhausted"},
    },
)
async def create_stream(
    request: Request, body: StreamRequestModel, orchestrator: OrchestratorDep, user_id: UserIdDep
):
    """
    Create an SSE streaming connection for real-time LLM responses.

    FASTAPI ROUTE DECORATOR EXPLAINED:
    -----------------------------------
    @router.post("") defines a POST endpoint at the router's prefix path.
    Since the router has prefix="/stream", this creates POST /stream

    ASYNC ROUTE HANDLERS:
    ---------------------
    Using 'async def' tells FastAPI this is an asynchronous handler.
    FastAPI will:
    - Run it in the async event loop (no blocking)
    - Allow concurrent request handling
    - Support 'await' for async operations

    PARAMETER INJECTION (Dependency Injection):
    -------------------------------------------
    FastAPI automatically injects parameters based on their type and location:

    1. request: Request
       - Special FastAPI type, automatically injected
       - Gives access to headers, client info, app state, etc.

    2. body: StreamRequestModel
       - Pydantic model → FastAPI parses JSON body into this model
       - Automatically validated before the function runs
       - If validation fails, returns 422 with error details

    3. orchestrator: OrchestratorDep
       - Custom dependency (defined in dependencies.py)
       - FastAPI calls get_orchestrator(request) and injects the result
       - This is dependency injection in action!

    4. user_id: UserIdDep
       - Custom dependency for user identification
       - ENTERPRISE BEST PRACTICE: Centralized user ID extraction
       - Automatically gets X-User-ID header or falls back to IP address

    Returns:
        StreamingResponse: SSE event stream with LLM response chunks

    SSE Event Format:
        event: message
        data: {"content": "token"}

        event: error
        data: {"error": "error_type", "message": "description"}

        data: [DONE]
    """

    # ========================================================================
    # STEP 1: Extract Request Context
    # ========================================================================
    # Get or generate a unique thread ID for request correlation.
    # This allows us to trace a request through logs, metrics, and debugging.
    thread_id = request.headers.get(HEADER_THREAD_ID) or str(uuid.uuid4())

    logger.info(
        "stream_request_received",
        thread_id=thread_id,
        user_id=user_id,
        model=body.model,
        provider=body.provider,
        query_length=len(body.query),
    )

    # ========================================================================
    # STEP 2: Delegate to Streaming Service
    # ========================================================================
    # The service handles all business logic:
    # - Connection pool management
    # - Queue failover if pool exhausted
    # - SSE event generation
    # - Error handling and metrics
    #
    # SEPARATION OF CONCERNS:
    # - Route: HTTP handling (validation, response formatting)
    # - Service: Business logic (streaming, failover, metrics)
    # - Models: Data validation (Pydantic schemas)

    try:
        service = get_streaming_service(orchestrator)

        # Create stream and get resilience layer indicator
        stream_generator, resilience_layer = await service.create_stream(
            request_model=body,
            user_id=user_id,
            thread_id=thread_id,
        )

        logger.debug("stream_started", thread_id=thread_id, resilience_layer=resilience_layer.value)

    except Exception as e:
        # ====================================================================
        # Service Layer Failed - Return 503
        # ====================================================================
        # If the service layer itself fails to start the stream,
        # return a proper HTTP error (not an SSE error event).
        logger.error(
            "stream_service_failed", thread_id=thread_id, error=str(e), error_type=type(e).__name__
        )

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "service_unavailable",
                "message": "Unable to start stream. Please try again later.",
            },
            headers={HEADER_THREAD_ID: thread_id},
        )

    # ========================================================================
    # STEP 3: Return StreamingResponse
    # ========================================================================
    # FASTAPI StreamingResponse:
    # --------------------------
    # StreamingResponse is a special response type for streaming data.
    # It takes an async generator and streams its output to the client.
    #
    # How it works:
    # 1. FastAPI sends the HTTP headers immediately
    # 2. For each value yielded by the generator:
    #    - FastAPI sends it to the client
    #    - The client receives it in real-time
    # 3. When the generator completes, FastAPI closes the connection
    #
    # Benefits of streaming:
    # - Lower latency (client sees data immediately)
    # - Lower memory usage (don't buffer entire response)
    # - Better user experience (progressive loading)

    return StreamingResponse(
        stream_generator,  # The async generator from StreamingService
        media_type="text/event-stream",  # SSE content type
        headers={
            # ================================================================
            # Thread ID: Request Correlation
            # ================================================================
            # Return the thread ID so client can correlate requests/responses.
            # Useful for debugging and support tickets.
            HEADER_THREAD_ID: thread_id,
            # ================================================================
            # Cache-Control: Prevent Caching
            # ================================================================
            # SSE streams are unique per request and shouldn't be cached.
            # This tells browsers and proxies not to cache the response.
            "Cache-Control": "no-cache",
            # ================================================================
            # Connection: Keep Alive
            # ================================================================
            # Keep the connection alive for streaming.
            # Prevents proxies from closing the connection prematurely.
            "Connection": "keep-alive",
            # ================================================================
            # X-Accel-Buffering: Disable NGINX Buffering
            # ================================================================
            # Some reverse proxies buffer responses, which breaks streaming.
            # This header tells NGINX to send data immediately.
            "X-Accel-Buffering": "no",
            # ================================================================
            # X-Resilience-Layer: Indicate Which Layer Handled Request
            # ================================================================
            # Tells the client which resilience layer was used:
            # - "1-Direct": Normal path (pool had capacity)
            # - "3-Queue-Failover": Request was queued (pool was full)
            "X-Resilience-Layer": resilience_layer.value,
        },
    )
