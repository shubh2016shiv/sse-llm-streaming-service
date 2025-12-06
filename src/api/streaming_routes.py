"""
Streaming Routes

This module contains SSE streaming endpoints.
"""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.config.constants import HEADER_THREAD_ID
from src.core.exceptions import SSEBaseError
from src.core.logging import get_logger
from src.monitoring import get_metrics_collector
from src.streaming import get_stream_lifecycle
from src.streaming.models import SSEEvent, StreamRequest

router = APIRouter(prefix="/stream", tags=["Streaming"])
logger = get_logger(__name__)


class StreamRequestModel(BaseModel):
    """SSE stream request model."""
    query: str = Field(..., min_length=1, max_length=100000, description="User query")
    model: str = Field(default="gpt-3.5-turbo", description="Model to use")
    provider: str | None = Field(default=None, description="Preferred provider")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Explain quantum computing in simple terms",
                "model": "gpt-3.5-turbo",
                "provider": "openai"
            }
        }


@router.post("")
async def create_stream(
    request: Request,
    body: StreamRequestModel
):
    """
    Create SSE streaming connection for LLM response.

    This endpoint:
    1. Validates the request
    2. Checks cache for existing response
    3. Verifies rate limits
    4. Selects provider with failover
    5. Streams response chunks
    6. Caches response and collects metrics

    Returns:
        StreamingResponse: SSE event stream
    """
    thread_id = request.headers.get(HEADER_THREAD_ID) or str(uuid.uuid4())

    # Get user identifier for rate limiting
    user_id = request.headers.get("X-User-ID") or request.client.host

    # Record request metric
    metrics = get_metrics_collector()
    metrics.increment_connections()

    async def event_generator():
        """Generate SSE events."""
        try:
            lifecycle = get_stream_lifecycle()

            stream_request = StreamRequest(
                query=body.query,
                model=body.model,
                provider=body.provider,
                thread_id=thread_id,
                user_id=user_id
            )

            async for event in lifecycle.stream(stream_request):
                yield event.format()

            # Send [DONE] signal
            yield "data: [DONE]\n\n"

            # Record success
            metrics.record_request("success", body.provider or "auto", body.model)

        except SSEBaseError as e:
            # Send error event
            error_event = SSEEvent(
                event="error",
                data={"error": type(e).__name__, "message": str(e)}
            )
            yield error_event.format()

            metrics.record_request("error", body.provider or "auto", body.model)
            metrics.record_error(type(e).__name__, "stream")

        except Exception as e:
            # Send generic error
            error_event = SSEEvent(
                event="error",
                data={"error": "internal_error", "message": "An unexpected error occurred"}
            )
            yield error_event.format()

            metrics.record_request("error", body.provider or "auto", body.model)
            metrics.record_error("internal_error", "stream")

            logger.error(
                "Unexpected error in stream",
                thread_id=thread_id,
                error=str(e)
            )

        finally:
            metrics.decrement_connections()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            HEADER_THREAD_ID: thread_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
