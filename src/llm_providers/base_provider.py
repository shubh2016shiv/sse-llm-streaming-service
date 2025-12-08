#!/usr/bin/env python3
"""
Base Provider Abstract Class

This module defines the abstract base class for all LLM providers.
Concrete implementations (OpenAI, DeepSeek, Gemini) inherit from this class.

Architectural Decision: Abstract base class for consistent patterns
- Common interface for all providers
- Built-in resilience (circuit breaker + retry)
- Execution tracking integration
- Structured error handling

Author: Senior Solution Architect
Date: 2025-12-05
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core.config.constants import LLMProvider
from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger
from src.core.observability.execution_tracker import get_tracker
from src.core.resilience.circuit_breaker import ResilientCall, get_circuit_breaker_manager

logger = get_logger(__name__)


@dataclass
class StreamChunk:
    """
    Represents a single chunk of streamed response.

    Attributes:
        content: Text content of the chunk
        finish_reason: Why streaming ended (if applicable)
        model: Model that generated the chunk
        usage: Token usage (if available)
        timestamp: When chunk was received
    """
    content: str
    finish_reason: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat() + 'Z'


@dataclass
class ProviderConfig:
    """
    Configuration for an LLM provider.

    Attributes:
        name: Provider name
        api_key: API key for authentication
        base_url: Base URL for API
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts
        default_model: Default model to use
    """
    name: str
    api_key: str
    base_url: str
    timeout: int = 30
    max_retries: int = 3
    default_model: str = ""


class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.

    STAGE-4: LLM provider base class

    This class provides:
    - Common interface for all providers
    - Built-in resilience (circuit breaker + retry)
    - Execution tracking integration
    - Health check standardization

    Subclasses must implement:
    - _stream_internal(): Core streaming logic
    - _validate_model(): Model validation
    - health_check(): Provider health check

    Usage:
        class OpenAIProvider(BaseProvider):
            async def _stream_internal(self, query, model, **kwargs):
                # OpenAI-specific implementation
                ...
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize base provider.

        STAGE-4.0: Provider initialization

        Args:
            config: Provider configuration
        """
        self.config = config
        self.name = config.name
        self._tracker = get_tracker()
        self._settings = get_settings()

        # Initialize resilience
        self._resilient_call = ResilientCall(
            provider_name=config.name,
            max_retries=config.max_retries
        )

        logger.info(
            "Provider initialized",
            stage="4.0",
            provider=config.name,
            base_url=config.base_url[:50] + "..." if len(config.base_url) > 50 else config.base_url
        )

    @property
    def provider_type(self) -> LLMProvider:
        """Get provider type enum."""
        return LLMProvider(self.name.lower())

    async def stream(
        self,
        query: str,
        model: str | None = None,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Stream response from LLM provider with resilience.

        STAGE-5: LLM streaming with resilience

        Args:
            query: User query
            model: Model to use (default from config)
            thread_id: Thread ID for tracking
            **kwargs: Additional provider-specific arguments

        Yields:
            StreamChunk: Individual response chunks

        Raises:
            ProviderError: On provider errors
            CircuitBreakerOpenError: If circuit is open
        """
        model = model or self.config.default_model

        # STAGE-5.1: Validate model
        if thread_id:
            with self._tracker.track_stage("5.1", f"Validate model: {model}", thread_id):
                self._validate_model(model)
        else:
            self._validate_model(model)

        # STAGE-5.2: Stream with resilience
        logger.info(
            "Starting stream",
            stage="5.2",
            provider=self.name,
            model=model,
            query_length=len(query)
        )

        try:
            # Stream chunks with execution tracking
            chunk_count = 0
            total_content_length = 0

            async for chunk in self._stream_internal(query, model, thread_id=thread_id, **kwargs):
                chunk_count += 1
                total_content_length += len(chunk.content)
                yield chunk

            logger.info(
                "Stream completed",
                stage="5.2",
                provider=self.name,
                chunk_count=chunk_count,
                total_length=total_content_length
            )

        except Exception as e:
            logger.error(
                "Stream failed",
                stage="5.2",
                provider=self.name,
                error_type=type(e).__name__,
                error=str(e)
            )
            raise

    @abstractmethod
    async def _stream_internal(
        self,
        query: str,
        model: str,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Internal streaming implementation.

        STAGE-5.3: Provider-specific streaming

        Subclasses must implement this method with provider-specific logic.

        Args:
            query: User query
            model: Model to use
            thread_id: Thread ID for tracking
            **kwargs: Additional arguments

        Yields:
            StreamChunk: Response chunks
        """
        pass

    @abstractmethod
    def _validate_model(self, model: str) -> None:
        """
        Validate that model is supported.

        STAGE-5.1.1: Model validation

        Args:
            model: Model name to validate

        Raises:
            InvalidModelError: If model not supported
        """
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check provider health.

        STAGE-4.H: Provider health check

        Returns:
            Dict with health status
        """
        pass

    async def get_circuit_state(self) -> str:
        """
        Get circuit breaker state for this provider.

        Returns:
            str: Circuit state (closed/open/half_open)
        """
        manager = get_circuit_breaker_manager()
        breaker = manager.get_breaker(self.name)
        return await breaker.get_state()

    async def get_stats(self) -> dict[str, Any]:
        """
        Get provider statistics.

        Returns:
            Dict with provider stats
        """
        # Get circuit breaker state directly
        # Note: manager.get_stats(name) does not exist, so we get state directly
        circuit_state = await self.get_circuit_state()

        return {
            "provider": self.name,
            "circuit_breaker": {"state": circuit_state},
            "config": {
                "timeout": self.config.timeout,
                "max_retries": self.config.max_retries,
                "default_model": self.config.default_model
            }
        }


class ProviderFactory:
    """
    Factory for creating LLM providers.

    STAGE-4.F: Provider factory

    This class provides:
    - Provider registration and creation
    - Lazy initialization
    - Provider caching

    Usage:
        factory = ProviderFactory()
        factory.register("openai", OpenAIProvider, config)

        provider = factory.get("openai")
        async for chunk in provider.stream("Hello"):
            print(chunk.content)
    """

    def __init__(self):
        """Initialize provider factory."""
        self._providers: dict[str, BaseProvider] = {}
        self._configs: dict[str, ProviderConfig] = {}
        self._classes: dict[str, type] = {}

        logger.info("Provider factory initialized", stage="4.F")

    def register(
        self,
        name: str,
        provider_class: type,
        config: ProviderConfig
    ) -> None:
        """
        Register a provider.

        Args:
            name: Provider name
            provider_class: Provider class (subclass of BaseProvider)
            config: Provider configuration
        """
        self._classes[name] = provider_class
        self._configs[name] = config

        logger.info(f"Registered provider: {name}", stage="4.F.1")

    def get(self, name: str) -> BaseProvider:
        """
        Get or create a provider.

        Args:
            name: Provider name

        Returns:
            BaseProvider: Provider instance

        Raises:
            ValueError: If provider not registered
        """
        if name not in self._classes:
            raise ValueError(f"Provider not registered: {name}")

        # Lazy initialization
        if name not in self._providers:
            self._providers[name] = self._classes[name](self._configs[name])

        return self._providers[name]

    def get_available(self) -> list[str]:
        """Get list of available providers."""
        return list(self._classes.keys())

    async def get_healthy_provider(self, exclude: list[str] | None = None) -> BaseProvider | None:
        """
        Get a healthy provider (circuit closed).

        STAGE-4.F.2: Provider failover selection

        Args:
            exclude: Providers to exclude

        Returns:
            BaseProvider or None if all unhealthy
        """
        exclude = exclude or []
        manager = get_circuit_breaker_manager()

        for name in self._classes.keys():
            if name in exclude:
                continue

            breaker = manager.get_breaker(name)
            state = await breaker.get_state()
            if state == "closed":
                return self.get(name)

        return None


# Global provider factory
_provider_factory: ProviderFactory | None = None


def get_provider_factory() -> ProviderFactory:
    """Get global provider factory."""
    global _provider_factory
    if _provider_factory is None:
        _provider_factory = ProviderFactory()
    return _provider_factory
