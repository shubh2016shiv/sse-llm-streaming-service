import json
import uuid
from copy import deepcopy
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RequestPriority(str, Enum):
    """
    Request priority levels for resource allocation.

    HIGH: Premium users, critical operations (gets priority processing)
    NORMAL: Standard users, regular requests (default)
    LOW: Background tasks, non-urgent operations (processes last)

    Rationale: Ensures premium users and critical operations get processed first,
    while maintaining fairness within each priority level.
    """
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class StreamRequest(BaseModel):
    """
    Represents an SSE streaming request.

    Includes priority field for resource allocation across instances.

    Rationale: Enables fair resource allocation - premium users get higher priority,
    allowing better QoS for high-value customers while still serving regular users.
    """
    model_config = {"frozen": True}
    query: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="User query",
    )
    model: str = Field(..., min_length=1, description="Model to use")
    provider: str | None = Field(default=None, description="Preferred provider")
    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Thread ID for correlation",
    )
    user_id: str | None = Field(
        default=None,
        description="User identifier for rate limiting",
    )
    priority: RequestPriority = Field(
        default=RequestPriority.NORMAL,
        description="Request priority (high/normal/low)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request metadata",
    )

    @classmethod
    def determine_priority(cls, is_premium_user: bool) -> RequestPriority:
        """
        Determine request priority based on user tier.

        Returns HIGH priority for premium users, NORMAL for others.
        """
        return RequestPriority.HIGH if is_premium_user else RequestPriority.NORMAL

    def __hash__(self):
        """Custom hash function to handle Dict fields."""
        # Use stable JSON representation for metadata
        metadata_str = json.dumps(self.metadata, sort_keys=True)
        return hash((
            self.query,
            self.model,
            self.provider,
            self.thread_id,
            self.user_id,
            self.priority,
            metadata_str
        ))

class SSEEvent(BaseModel):
    """
    Represents an SSE event to send to client.
    """
    model_config = {"frozen": True}

    event: str
    data: Any
    id: str | None = None

    @field_validator("data", mode="before")
    @classmethod
    def copy_data(cls, v):
        """Ensure data is copied to prevent mutation of original reference."""
        # Simple copy for dicts/lists to avoid reference issues
        if isinstance(v, dict | list):
            try:
                return deepcopy(v)
            except Exception:
                # Fallback if uncopyable
                return v
        return v

    def format(self) -> str:
        """Format as SSE protocol string."""
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")

        if isinstance(self.data, str):
            lines.append(f"data: {self.data}")
        else:
            lines.append(f"data: {json.dumps(self.data)}")

        return "\n".join(lines) + "\n\n"
