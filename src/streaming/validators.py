"""
Request Validators

Validates streaming request parameters including query content,
model specifications, and connection limits.
"""

from src.config.constants import MAX_CONCURRENT_CONNECTIONS
from src.core.exceptions import StreamingError, ValidationError


class RequestValidator:
    """Validates streaming request parameters."""

    def validate_query(self, query: str) -> None:
        """Validate query is non-empty and within size limits."""
        if not query or not query.strip():
            raise ValidationError(message="Query cannot be empty")

        if len(query) > 100000:  # 100KB limit
            raise ValidationError(message="Query too long (max 100KB)")

    def validate_model(self, model: str) -> None:
        """Validate model identifier is specified."""
        if not model or not model.strip():
            raise ValidationError(message="Model cannot be empty")

    def check_connection_limit(self, active_connections: int) -> None:
        """Verify connection limit is not exceeded."""
        if active_connections >= MAX_CONCURRENT_CONNECTIONS:
            raise StreamingError(
                message=f"Connection limit reached ({MAX_CONCURRENT_CONNECTIONS})"
            )

