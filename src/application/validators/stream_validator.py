"""
Stream Request Validators

Professional validators for streaming requests with comprehensive validation rules.

ENTERPRISE ARCHITECTURE: Separation of Concerns
------------------------------------------------
Each validator has a single responsibility:
- QueryValidator: Validates query content
- ModelValidator: Validates model identifiers
- ProviderValidator: Validates provider identifiers
- StreamRequestValidator: Orchestrates all validations

This makes the code:
- Easier to test (test each validator independently)
- Easier to maintain (changes are localized)
- Easier to extend (add new validators without touching existing ones)
"""

from src.application.validators.base import BaseValidator
from src.application.validators.exceptions import (
    ModelValidationError,
    ProviderValidationError,
    QueryValidationError,
)
from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class QueryValidator(BaseValidator):
    """
    Validates query content for streaming requests.

    VALIDATION RULES:
    -----------------
    1. Not empty or whitespace-only
    2. Length between 1 and 100,000 characters
    3. No malicious patterns (XSS, SQL injection, path traversal)

    ENTERPRISE DECISION: Query Length Limits
    -----------------------------------------
    - Min: 1 character (prevent empty queries)
    - Max: 100,000 characters (prevent DoS via large payloads)
    - Configurable via settings for different environments
    """

    # Default limits (can be overridden via settings)
    DEFAULT_MIN_LENGTH = 1
    DEFAULT_MAX_LENGTH = 100_000  # 100KB

    def __init__(self, strict: bool = True):
        super().__init__(strict)
        self.settings = get_settings()

        # Allow configuration override
        self.max_length = getattr(self.settings, "QUERY_MAX_LENGTH", self.DEFAULT_MAX_LENGTH)

    def validate(self, query: str) -> None:
        """
        Validate query content.

        Args:
            query: User query string

        Raises:
            QueryValidationError: If validation fails

        VALIDATION SEQUENCE:
        --------------------
        1. Check not empty (fail fast)
        2. Check length (prevent resource exhaustion)
        3. Check security patterns (prevent attacks)
        """
        try:
            # Step 1: Not empty
            self.validate_not_empty(query, "query")

            # Step 2: Length limits
            self.validate_length(
                query, "query", min_length=self.DEFAULT_MIN_LENGTH, max_length=self.max_length
            )

            # Step 3: Security checks
            self.check_security_patterns(query, "query")

            logger.debug("Query validation passed", query_length=len(query))

        except Exception as e:
            # Convert generic ValidationError to QueryValidationError
            if not isinstance(e, QueryValidationError):
                raise QueryValidationError(str(e), field="query") from e
            raise


class ModelValidator(BaseValidator):
    """
    Validates model identifiers.

    VALIDATION RULES:
    -----------------
    1. Not empty or whitespace-only
    2. Matches known model patterns or exact names
    3. Provider-specific validation (optional)

    ENTERPRISE DECISION: Model Whitelist
    -------------------------------------
    We maintain a whitelist of known models for security:
    - Prevents arbitrary model injection
    - Ensures only tested models are used
    - Easy to add new models (update whitelist)
    - Can be extended with provider-specific validation
    """

    # Known valid models (grouped by provider for clarity)
    OPENAI_MODELS = {
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-16k",
        "gpt-3.5-turbo-0125",
        "gpt-4",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4o",
        "gpt-4o-mini",
    }

    ANTHROPIC_MODELS = {
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-sonnet-20241022",
        # Simplified names
        "claude-3-opus",
        "claude-3-sonnet",
        "claude-3-haiku",
        "claude-3-5-sonnet",
    }

    GOOGLE_MODELS = {
        "gemini-pro",
        "gemini-pro-vision",
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
    }

    DEEPSEEK_MODELS = {
        "deepseek-chat",
        "deepseek-coder",
    }

    # Combined whitelist
    VALID_MODELS = OPENAI_MODELS | ANTHROPIC_MODELS | GOOGLE_MODELS | DEEPSEEK_MODELS

    def validate(self, model: str, provider: str | None = None) -> None:
        """
        Validate model identifier.

        Args:
            model: Model identifier
            provider: Provider name (optional, for provider-specific validation)

        Raises:
            ModelValidationError: If validation fails

        VALIDATION LOGIC:
        -----------------
        1. Check not empty
        2. Check against whitelist
        3. If provider specified, validate model belongs to that provider
        """
        try:
            # Step 1: Not empty
            self.validate_not_empty(model, "model")

            # Step 2: Whitelist validation
            self.validate_whitelist(model, self.VALID_MODELS, "model", case_sensitive=True)

            # Step 3: Provider-specific validation (if provider specified)
            if provider:
                self._validate_model_for_provider(model, provider)

            logger.debug("Model validation passed", model=model, provider=provider)

        except Exception as e:
            if not isinstance(e, ModelValidationError):
                raise ModelValidationError(str(e), field="model", value=model) from e
            raise

    def _validate_model_for_provider(self, model: str, provider: str) -> None:
        """
        Validate model belongs to specified provider.

        ENTERPRISE PATTERN: Provider-Model Mapping
        -------------------------------------------
        Ensures consistency between provider and model:
        - Prevents using OpenAI models with Anthropic provider
        - Catches configuration errors early
        - Provides clear error messages
        """
        provider_models = {
            "openai": self.OPENAI_MODELS,
            "anthropic": self.ANTHROPIC_MODELS,
            "google": self.GOOGLE_MODELS,
            "deepseek": self.DEEPSEEK_MODELS,
        }

        provider_lower = provider.lower()
        if provider_lower in provider_models:
            if model not in provider_models[provider_lower]:
                raise ModelValidationError(
                    f"Model '{model}' is not valid for provider '{provider}'",
                    field="model",
                    value=model,
                )


class ProviderValidator(BaseValidator):
    """
    Validates provider identifiers.

    VALIDATION RULES:
    -----------------
    1. Not empty (if specified)
    2. Matches known provider names
    3. Provider is enabled in configuration
    """

    VALID_PROVIDERS = {
        "openai",
        "anthropic",
        "google",
        "deepseek",
    }

    def validate(self, provider: str | None) -> None:
        """
        Validate provider identifier.

        Args:
            provider: Provider name (optional)

        Raises:
            ProviderValidationError: If validation fails

        NOTE: Provider is optional (auto-selected if not specified)
        """
        # Provider is optional
        if provider is None:
            return

        try:
            # Check not empty
            self.validate_not_empty(provider, "provider")

            # Whitelist validation (case-insensitive)
            self.validate_whitelist(
                provider, self.VALID_PROVIDERS, "provider", case_sensitive=False
            )

            logger.debug("Provider validation passed", provider=provider)

        except Exception as e:
            if not isinstance(e, ProviderValidationError):
                raise ProviderValidationError(str(e), field="provider", value=provider) from e
            raise


class StreamRequestValidator:
    """
    Orchestrates validation for complete stream requests.

    ENTERPRISE PATTERN: Facade Pattern
    -----------------------------------
    Provides a simple interface for validating entire requests:
    - Hides complexity of individual validators
    - Ensures all validations run in correct order
    - Provides single point of entry for request validation

    Usage:
        validator = StreamRequestValidator()
        validator.validate_request(
            query="What is AI?",
            model="gpt-3.5-turbo",
            provider="openai"
        )
    """

    def __init__(self, strict: bool = True):
        """
        Initialize request validator with sub-validators.

        Args:
            strict: If True, fail on any validation error
        """
        self.query_validator = QueryValidator(strict=strict)
        self.model_validator = ModelValidator(strict=strict)
        self.provider_validator = ProviderValidator(strict=strict)

    def validate_request(self, query: str, model: str, provider: str | None = None) -> None:
        """
        Validate complete stream request.

        Args:
            query: User query
            model: Model identifier
            provider: Provider name (optional)

        Raises:
            ValidationError: If any validation fails

        VALIDATION ORDER:
        -----------------
        1. Query (most likely to fail, fail fast)
        2. Model (required field)
        3. Provider (optional field)
        4. Model-Provider consistency (if provider specified)
        """
        # Validate query
        self.query_validator.validate(query)

        # Validate provider (if specified)
        self.provider_validator.validate(provider)

        # Validate model (with provider context)
        self.model_validator.validate(model, provider)

        logger.info(
            "Stream request validation passed",
            query_length=len(query),
            model=model,
            provider=provider,
        )

    def validate_query(self, query: str) -> None:
        """
        Validate query content.

        Convenience method for validating just the query.

        Args:
            query: User query string

        Raises:
            QueryValidationError: If validation fails
        """
        self.query_validator.validate(query)

    def validate_model(self, model: str, provider: str | None = None) -> None:
        """
        Validate model identifier.

        Convenience method for validating just the model.

        Args:
            model: Model identifier
            provider: Provider name (optional, for provider-specific validation)

        Raises:
            ModelValidationError: If validation fails
        """
        self.model_validator.validate(model, provider)

    def check_connection_limit(self, current_connections: int) -> None:
        """
        Check if connection limit would be exceeded.

        Args:
            current_connections: Current number of active connections

        Raises:
            ValidationError: If connection limit would be exceeded
        """
        # Get max connections from settings with fallback to constant
        from src.core.config.constants import MAX_CONCURRENT_CONNECTIONS
        from src.core.config.settings import get_settings

        settings = get_settings()
        max_connections = getattr(settings.app, "MAX_CONNECTIONS", MAX_CONCURRENT_CONNECTIONS)

        if current_connections >= max_connections:
            from src.application.validators.exceptions import ValidationError

            raise ValidationError(
                f"Connection limit exceeded: {current_connections}/{max_connections}",
                field="connections",
            )
