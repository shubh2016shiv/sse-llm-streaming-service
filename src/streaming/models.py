import json
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    query: str = Field(..., min_length=1, max_length=100000, description="User query")
    model: str = Field(..., min_length=1, description="Model to use")
    provider: str | None = Field(default=None, description="Preferred provider")
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Thread ID for correlation")
    user_id: str | None = Field(default=None, description="User identifier for rate limiting")
    priority: RequestPriority = Field(
        default=RequestPriority.NORMAL,
        description="Request priority (high/normal/low)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional request metadata")

    @classmethod
    def determine_priority(cls, is_premium_user: bool) -> RequestPriority:
        """
        Determine request priority based on user tier.

        Returns HIGH priority for premium users, NORMAL for others.
        """
        return RequestPriority.HIGH if is_premium_user else RequestPriority.NORMAL

class SSEEvent(BaseModel):
    """
    Represents an SSE event to send to client.
    """
    event: str
    data: Any
    id: str | None = None

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
