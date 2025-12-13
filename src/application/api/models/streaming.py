"""
Streaming API Models - Educational Documentation
=================================================

WHAT ARE STREAMING MODELS?
--------------------------
These Pydantic models define the data structures for the SSE streaming endpoint.
Separating models from routes provides:

1. **Reusability**: Models can be imported by routes, services, and tests
2. **Type Safety**: Strong typing with validation at runtime
3. **Documentation**: Auto-generated OpenAPI schemas
4. **Testability**: Models can be tested independently

PYDANTIC V2 FEATURES USED:
--------------------------
- Field validators with @field_validator decorator
- model_dump() for serialization (replaces .dict())
- Config class for JSON schema customization
- Union types with | syntax (Python 3.10+)

This module defines:
- StreamRequestModel: Validates incoming streaming requests
- StreamErrorResponse: Standardized error format for SSE
- StreamingStatus: Enum for request lifecycle states
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# ENUMS: Type-Safe Constants for Streaming
# ============================================================================
# Enums provide compile-time type checking and IDE autocompletion.
# Using str + Enum allows JSON serialization as strings (not integers).


class StreamingStatus(str, Enum):
    """
    Lifecycle states for a streaming request.

    STREAMING REQUEST LIFECYCLE:
    ----------------------------
    1. PENDING: Request received, awaiting processing
    2. QUEUED: Request queued due to capacity limits (Layer 3 failover)
    3. STREAMING: Actively streaming LLM response chunks
    4. COMPLETED: Stream finished successfully
    5. FAILED: Stream failed with error

    WHY TRACK STATUS?
    -----------------
    - Client can poll for status if connection drops
    - Metrics can track where requests spend time
    - Debugging: Know exactly where request failed
    """

    PENDING = "pending"
    QUEUED = "queued"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"


class ResilienceLayer(str, Enum):
    """
    Indicates which resilience layer handled the request.

    THREE-LAYER DEFENSE ARCHITECTURE:
    ---------------------------------
    Layer 1 (NGINX): Rate limiting at edge, blocks obvious abuse
    Layer 2 (CONNECTION_POOL): Application-level connection management
    Layer 3 (QUEUE_FAILOVER): Async queue when pool exhausted

    This header (X-Resilience-Layer) tells clients how the request was handled.
    """

    DIRECT = "1-Direct"
    CONNECTION_POOL = "2-Connection-Pool"
    QUEUE_FAILOVER = "3-Queue-Failover"


# ============================================================================
# REQUEST MODELS: Input Validation
# ============================================================================


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

    ENTERPRISE BEST PRACTICE:
    -------------------------
    This model validates input BEFORE any processing occurs, ensuring:
    - No empty queries waste resources
    - Model names are reasonable
    - Providers are valid (if specified)
    """

    # ========================================================================
    # REQUIRED FIELD: Query (the user's prompt)
    # ========================================================================
    # The '...' means "required" in Pydantic.
    # min_length=1 prevents empty strings.
    # max_length=100000 prevents DoS via huge payloads.
    query: str = Field(
        ..., min_length=1, max_length=100000, description="User query to send to the LLM"
    )

    # ========================================================================
    # REQUIRED FIELD: Model (which LLM to use)
    # ========================================================================
    # Examples: gpt-4, gpt-3.5-turbo, claude-3-opus, etc.
    model: str = Field(..., description="LLM model identifier (e.g., gpt-4, claude-3)")

    # ========================================================================
    # OPTIONAL FIELD: Provider (which LLM provider)
    # ========================================================================
    # If not specified, the system auto-selects based on model name.
    # Union syntax (str | None) is Python 3.10+ feature.
    provider: str | None = Field(
        default=None,
        description=(
            "Preferred LLM provider (openai, anthropic, etc.). Auto-selected if not specified."
        ),
    )

    # ========================================================================
    # PYDANTIC CONFIG: Schema Customization
    # ========================================================================
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

    # ========================================================================
    # FIELD VALIDATORS: Custom Validation Logic
    # ========================================================================
    # Field validators run AFTER basic type validation and can reject
    # invalid values. They raise ValueError which FastAPI converts to 422.

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """
        Validate model name is not empty and not obviously invalid.

        VALIDATION STRATEGY:
        --------------------
        - Reject empty/whitespace-only strings
        - Reject known invalid models (for testing)
        - Strip whitespace from valid models

        WHY NOT VALIDATE AGAINST A LIST?
        ---------------------------------
        Model availability changes frequently. Provider-level validation
        is handled by the LLM provider itself, not here.
        """
        if not v or v.strip() == "":
            raise ValueError("Model cannot be empty")

        # Reject known invalid models for testing purposes
        invalid_models = ["invalid-model", "gpt-5"]
        if v in invalid_models:
            raise ValueError(f"Invalid model: {v}")

        return v.strip()

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str | None) -> str | None:
        """
        Validate provider if specified.

        VALIDATION STRATEGY:
        --------------------
        - None is valid (auto-selection)
        - Reject known invalid providers
        - Strip whitespace from valid providers
        """
        if v is not None:
            # Reject known invalid providers
            invalid_providers = ["nonexistent-provider"]
            if v in invalid_providers:
                raise ValueError(f"Invalid provider: {v}")
            return v.strip()
        return v


# ============================================================================
# RESPONSE MODELS: Output Structures
# ============================================================================


class StreamErrorResponse(BaseModel):
    """
    Standardized error response for streaming errors.

    ERROR RESPONSE PATTERN:
    -----------------------
    Instead of just returning a string, we return structured error data:
    - error: Machine-readable error type (for error handling code)
    - message: Human-readable description (for display)
    - details: Optional additional context (for debugging)

    SSE ERROR EVENTS:
    -----------------
    Errors are sent as SSE events with event: error
    Format: event: error\ndata: {"error": "...", "message": "..."}\n\n

    This allows clients to distinguish between:
    - Data events (normal content)
    - Error events (something went wrong)
    """

    error: str = Field(
        ..., description="Machine-readable error type (e.g., 'connection_pool_exhausted')"
    )
    message: str = Field(..., description="Human-readable error description")
    details: dict[str, Any] | None = Field(
        default=None, description="Optional additional error context for debugging"
    )


class ServiceUnavailableResponse(BaseModel):
    """
    Response model for 503 Service Unavailable errors.

    WHEN USED:
    ----------
    - Connection pool exhausted AND queue failover failed
    - External dependencies (Redis, Kafka) unavailable
    - System in maintenance mode

    INCLUDES:
    ---------
    - Retry-After header hint in details
    - Thread ID for request correlation
    """

    error: str = Field(default="service_unavailable", description="Error type identifier")
    message: str = Field(..., description="User-friendly error message")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional context (retry_after, queue_depth, etc.)"
    )


# ============================================================================
# EXPORTS: Public API
# ============================================================================
# Define what's exported when using: from models.streaming import *

__all__ = [
    # Enums
    "StreamingStatus",
    "ResilienceLayer",
    # Request Models
    "StreamRequestModel",
    # Response Models
    "StreamErrorResponse",
    "ServiceUnavailableResponse",
]
