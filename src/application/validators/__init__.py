"""
Application Validators Module

Professional validation framework for the SSE streaming application.

ENTERPRISE ARCHITECTURE: Validation Layer
------------------------------------------
This module provides a comprehensive validation framework with:
- Custom exception hierarchy for precise error handling
- Base validator class with reusable utilities
- Specialized validators for different domains
- Separation of concerns (each validator has single responsibility)

USAGE EXAMPLES:
---------------

1. Stream Request Validation:
    from src.application.validators import StreamRequestValidator

    validator = StreamRequestValidator()
    validator.validate_request(
        query="What is AI?",
        model="gpt-3.5-turbo",
        provider="openai"
    )

2. Individual Field Validation:
    from src.application.validators import QueryValidator, ModelValidator

    query_validator = QueryValidator()
    query_validator.validate("What is quantum computing?")

    model_validator = ModelValidator()
    model_validator.validate("gpt-4", provider="openai")

3. Configuration Validation:
    from src.application.validators import ConfigValidator

    config_validator = ConfigValidator()
    config_validator.validate({
        "USE_FAKE_LLM": True,
        "ENABLE_CACHING": False
    })

4. Exception Handling:
    from src.application.validators import (
        StreamRequestValidator,
        QueryValidationError,
        ModelValidationError
    )

    try:
        validator.validate_request(...)
    except QueryValidationError as e:
        # Handle query-specific errors
        print(f"Query error: {e.message}")
    except ModelValidationError as e:
        # Handle model-specific errors
        print(f"Model error: {e.message}")

DESIGN PATTERNS USED:
---------------------
1. Template Method: BaseValidator provides common utilities
2. Facade: StreamRequestValidator orchestrates multiple validators
3. Exception Hierarchy: Specific exceptions for precise error handling
4. Separation of Concerns: Each validator has single responsibility
"""

# Exception classes
# Base validator
from src.application.validators.base import BaseValidator
from src.application.validators.config_validator import ConfigValidator
from src.application.validators.exceptions import (
    ConfigValidationError,
    ModelValidationError,
    ProviderValidationError,
    QueryValidationError,
    RateLimitValidationError,
    SecurityValidationError,
    ValidationError,
)

# Specialized validators
from src.application.validators.stream_validator import (
    ModelValidator,
    ProviderValidator,
    QueryValidator,
    StreamRequestValidator,
)


# Backward compatibility with old RequestValidator
# DEPRECATED: Use StreamRequestValidator instead
class RequestValidator(StreamRequestValidator):
    """
    Backward compatibility wrapper for old RequestValidator.

    DEPRECATED: This class is maintained for backward compatibility only.
    New code should use StreamRequestValidator instead.

    Migration Guide:
    ----------------
    Old:
        from src.application.validators.stream_validator import RequestValidator
        validator = RequestValidator()
        validator.validate_query(query)
        validator.validate_model(model)

    New:
        from src.application.validators import StreamRequestValidator
        validator = StreamRequestValidator()
        validator.validate_request(query=query, model=model, provider=provider)
    """

    def validate_query(self, query: str) -> None:
        """Validate query (backward compatibility)."""
        self.query_validator.validate(query)

    def validate_model(self, model: str) -> None:
        """Validate model (backward compatibility)."""
        self.model_validator.validate(model)

    def check_connection_limit(self, active_connections: int) -> None:
        """
        Check connection limit (backward compatibility).

        NOTE: This method is deprecated. Connection limiting should be
        handled by rate limiting middleware, not validators.
        """
        from src.core.config.constants import MAX_CONCURRENT_CONNECTIONS
        from src.core.config.settings import get_settings

        settings = get_settings()
        max_connections = getattr(settings.app, 'MAX_CONNECTIONS', MAX_CONCURRENT_CONNECTIONS)

        if active_connections >= max_connections:
            raise RateLimitValidationError(
                f"Connection limit reached ({max_connections})",
                field="connections"
            )


# Public API
__all__ = [
    # Exceptions
    "ValidationError",
    "QueryValidationError",
    "ModelValidationError",
    "ProviderValidationError",
    "RateLimitValidationError",
    "SecurityValidationError",
    "ConfigValidationError",
    # Base
    "BaseValidator",
    # Validators
    "QueryValidator",
    "ModelValidator",
    "ProviderValidator",
    "StreamRequestValidator",
    "ConfigValidator",
    # Backward compatibility
    "RequestValidator",
]
