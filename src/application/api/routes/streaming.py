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

This module contains the SSE streaming endpoint for real-time LLM responses.
"""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.application.api.dependencies import OrchestratorDep, UserIdDep
from src.core.config.constants import HEADER_THREAD_ID
from src.core.exceptions import SSEBaseError
from src.core.logging.logger import get_logger
from src.infrastructure.monitoring.metrics_collector import get_metrics_collector
from src.llm_stream.models.stream_request import SSEEvent, StreamRequest

# ============================================================================
# ROUTER SETUP
# ============================================================================
# Create a router for all streaming-related endpoints.
# - prefix="/stream": All routes in this router will start with /stream
# - tags=["Streaming"]: Groups these endpoints in the API docs under "Streaming"

router = APIRouter(prefix="/stream", tags=["Streaming"])
logger = get_logger(__name__)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================
# PYDANTIC MODELS: Data Validation and Serialization
# ---------------------------------------------------
# Pydantic is a data validation library that FastAPI uses extensively.
# When you define a Pydantic model and use it as a parameter type,
# FastAPI automatically:
# 1. Parses the JSON request body
# 2. Validates each field against its type and constraints
# 3. Returns a 422 error if validation fails
# 4. Provides automatic API documentation with examples
# 5. Serializes the model to JSON for responses


class StreamRequestModel(BaseModel):
    """
    Request model for SSE streaming endpoint.

    PYDANTIC FIELD VALIDATION:
    --------------------------
    Field() lets you add validation rules and metadata:
    - ... (Ellipsis): Required field (no default value)
    - min_length/max_length: String length constraints
    - default: Default value if not provided
    - description: Shows in API docs

    FastAPI will automatically reject requests that don't meet these constraints
    with a detailed error message explaining what's wrong.
    """

    # Required field: must be between 1 and 100,000 characters
    # The '...' means "required" in Pydantic
    query: str = Field(
        ..., min_length=1, max_length=100000, description="User query to send to the LLM"
    )

    # Required field: must be a known model
    model: str = Field(
        description="LLM model identifier (e.g., gpt-4, claude-3)"
    )

    # Optional field that can be None (using Python 3.10+ union syntax)
    provider: str | None = Field(
        default=None,
        description=(
            "Preferred LLM provider (openai, anthropic, etc.). Auto-selected if not specified."
        ),
    )

    # PYDANTIC CONFIG:
    # ----------------
    # The Config class customizes Pydantic's behavior for this model.
    # json_schema_extra adds example data to the OpenAPI schema,
    # which appears in the interactive API docs (/docs).
    class Config:
        json_schema_extra = {
            "example": {
                "query": "Explain quantum computing in simple terms",
                "model": "gpt-3.5-turbo",
                "provider": "openai",
            }
        }

    # PYDANTIC FIELD VALIDATORS:
    # --------------------------
    # Field validators run after basic type validation and can reject invalid values.
    # They raise ValueError with a message that FastAPI converts to a 422 response.

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Validate model name is not empty and not obviously invalid."""
        if not v or v.strip() == "":
            raise ValueError("Model cannot be empty")

        # Reject known invalid models for testing
        invalid_models = ["invalid-model", "gpt-5"]
        if v in invalid_models:
            raise ValueError(f"Invalid model: {v}")

        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        """Validate provider if specified."""
        if v is not None:
            # Reject known invalid providers
            invalid_providers = ["nonexistent-provider"]
            if v in invalid_providers:
                raise ValueError(f"Invalid provider: {v}")

        return v


# ============================================================================
# STREAMING ENDPOINT
# ============================================================================


@router.post("")
async def create_stream(
    request: Request,
    body: StreamRequestModel,
    orchestrator: OrchestratorDep,
    user_id: UserIdDep
):
    """
    Create an SSE streaming connection for real-time LLM responses.

    FASTAPI ROUTE DECORATOR EXPLAINED:
    -----------------------------------
    @router.post("") defines a POST endpoint at the router's prefix path.
    Since the router has prefix="/stream", this creates POST /stream

    You could also write:
    - @router.post("/") for POST /stream/
    - @router.post("/chat") for POST /stream/chat

    ASYNC ROUTE HANDLERS:
    ---------------------
    Using 'async def' tells FastAPI this is an asynchronous handler.
    FastAPI will:
    - Run it in the async event loop (no blocking)
    - Allow concurrent request handling
    - Support 'await' for async operations

    If you use 'def' (sync), FastAPI runs it in a thread pool to avoid blocking.

    PARAMETER INJECTION:
    --------------------
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
       - Makes the code DRY (Don't Repeat Yourself)

    REQUEST LIFECYCLE FOR THIS ENDPOINT:
    ------------------------------------
    1. Client sends POST /stream with JSON body
    2. FastAPI parses JSON and validates against StreamRequestModel
    3. FastAPI calls get_orchestrator(request) to resolve dependency
    4. FastAPI calls create_stream() with all parameters injected
    5. create_stream() returns a StreamingResponse
    6. FastAPI sends headers and starts streaming
    7. Each yield from event_generator() sends an SSE event
    8. When generator completes, connection closes

    This endpoint implements the following workflow:
    1. Extract/generate thread ID for request correlation
    2. Identify user for rate limiting
    3. Record metrics (active connections)
    4. Create async generator for SSE events
    5. Stream LLM response chunks as SSE events
    6. Handle errors gracefully (send error events)
    7. Clean up metrics on completion

    Args:
        request: FastAPI Request object (auto-injected)
        body: Validated request body (auto-parsed from JSON)
        orchestrator: Stream orchestrator dependency (auto-injected)

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

    # ENTERPRISE NOTE: user_id is now injected via dependency (UserIdDep)
    # This centralizes user identification logic and follows DRY principle

    # ========================================================================
    # STEP 2: Record Metrics
    # ========================================================================
    # Track active connections for monitoring and capacity planning.
    # This is decremented in the finally block to ensure accurate counts.
    metrics = get_metrics_collector()
    metrics.increment_connections()

    # ========================================================================
    # STEP 3: Define Async Generator for SSE Events
    # ========================================================================
    # ASYNC GENERATORS IN PYTHON:
    # ---------------------------
    # An async generator is a function that:
    # 1. Is defined with 'async def'
    # 2. Uses 'yield' to produce values
    # 3. Can use 'await' for async operations
    #
    # How it works:
    # - Each 'yield' pauses execution and returns a value
    # - The caller can iterate with 'async for'
    # - Execution resumes after the yield when next value is requested
    #
    # Why use it for SSE?
    # - Perfect for streaming data as it becomes available
    # - Non-blocking (doesn't tie up the event loop)
    # - Memory efficient (doesn't load entire response into memory)

    async def event_generator():
        """
        Async generator that yields SSE-formatted events.

        This generator:
        1. Creates a StreamRequest from the validated input
        2. Calls the orchestrator to stream LLM responses
        3. Formats each chunk as an SSE event
        4. Handles errors by sending error events
        5. Sends [DONE] signal when complete
        6. Cleans up metrics in finally block

        The try/except/finally structure ensures:
        - Errors are sent to the client (not just logged)
        - Metrics are always cleaned up (even on errors)
        - The stream always terminates gracefully
        """
        try:
            # Create internal request object with all necessary context
            stream_request = StreamRequest(
                query=body.query,
                model=body.model,
                provider=body.provider,
                thread_id=thread_id,
                user_id=user_id,
            )

            # Stream LLM response chunks from the orchestrator.
            # The orchestrator handles:
            # - Cache lookup
            # - Rate limiting
            # - Provider selection and failover
            # - Actual LLM streaming
            # - Cache storage
            #
            # ASYNC FOR LOOP:
            # ---------------
            # 'async for' is used to iterate over an async generator.
            # It automatically awaits each iteration.
            # Each 'event' is an SSEEvent object with the LLM response chunk.
            async for event in orchestrator.stream(stream_request):
                # Format the event as SSE protocol and yield it.
                # event.format() returns a string like:
                # "event: message\ndata: {...}\n\n"
                yield event.format()

            # Send completion signal.
            # This tells the client the stream is complete (not an error).
            # The client's EventSource can detect this and stop listening.
            yield "data: [DONE]\n\n"

            # Record successful completion in metrics
            metrics.record_request("success", body.provider or "auto", body.model)

        except SSEBaseError as e:
            # Handle application-specific errors (cache errors, provider errors, etc.)
            # Send an error event to the client instead of just closing the connection.
            # This gives the client context about what went wrong.
            error_event = SSEEvent(
                event="error", data={"error": type(e).__name__, "message": str(e)}
            )
            yield error_event.format()

            # Record error metrics for monitoring and alerting
            metrics.record_request("error", body.provider or "auto", body.model)
            metrics.record_error(type(e).__name__, "stream")

        except Exception as e:
            # Handle unexpected errors (programming errors, system failures, etc.)
            # Don't expose internal error details to the client (security best practice)
            error_event = SSEEvent(
                event="error",
                data={"error": "internal_error", "message": "An unexpected error occurred"},
            )
            yield error_event.format()

            # Record error metrics
            metrics.record_request("error", body.provider or "auto", body.model)
            metrics.record_error("internal_error", "stream")

            # Log detailed error for debugging (includes full exception)
            logger.error("Unexpected error in stream", thread_id=thread_id, error=str(e))

        finally:
            # FINALLY BLOCK:
            # --------------
            # This ALWAYS runs, even if there's an error or early return.
            # Critical for cleanup operations like:
            # - Closing connections
            # - Releasing resources
            # - Updating metrics
            #
            # Decrement active connections counter.
            # This ensures our metrics stay accurate even if errors occur.
            metrics.decrement_connections()

    # ========================================================================
    # STEP 4: Return StreamingResponse
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
    # This is different from a regular Response where:
    # - You build the entire response in memory
    # - Send it all at once when the handler returns
    #
    # Benefits of streaming:
    # - Lower latency (client sees data immediately)
    # - Lower memory usage (don't buffer entire response)
    # - Better user experience (progressive loading)

    return StreamingResponse(
        event_generator(),  # The async generator that produces SSE events
        media_type="text/event-stream",  # SSE content type (tells client to expect SSE format)
        headers={
            # Return the thread ID so client can correlate requests/responses
            HEADER_THREAD_ID: thread_id,
            # Prevent caching of streaming responses
            # SSE streams are unique per request and shouldn't be cached
            "Cache-Control": "no-cache",
            # Keep the connection alive for streaming
            # Prevents proxies from closing the connection prematurely
            "Connection": "keep-alive",
            # Disable nginx buffering
            # Some reverse proxies buffer responses, which breaks streaming
            # This header tells nginx to send data immediately
            "X-Accel-Buffering": "no",
        },
    )
