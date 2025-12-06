#!/usr/bin/env python3
"""
OpenAI LLM Provider Implementation

This module implements the OpenAI provider using the official AsyncOpenAI client.
It handles authentication, streaming, and error mapping to the internal exception hierarchy.

Architectural Decision: Use official SDK
- Provides best compatibility with OpenAI features
- Handles connection pooling and retries internally (though we add our own layer)
- Type-safe responses

Author: Senior Solution Architect
Date: 2025-12-05
"""

import time
from collections.abc import AsyncGenerator
from typing import Any

from openai import APIConnectionError, APIError, AsyncOpenAI, AuthenticationError, RateLimitError

from src.core.exceptions import (
    ProviderAPIError,
    ProviderAuthenticationError,
    ProviderNotAvailableError,
    RateLimitExceededError,
)
from src.core.logging import get_logger
from src.llm_providers.base_provider import BaseProvider, ProviderConfig, StreamChunk

logger = get_logger(__name__)


class OpenAIProvider(BaseProvider):
    """
    Concrete implementation of the OpenAI LLM provider.

    STAGE-OPENAI: OpenAI provider operations

    This class implements the BaseProvider interface for OpenAI's API.
    It manages the AsyncOpenAI client lifecycle and translates OpenAI-specific
    exceptions into our internal standardized exception hierarchy.
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize the OpenAI provider.

        Args:
            config: Configuration object containing API key, base URL, etc.
        """
        super().__init__(config)

        # Initialize the official AsyncOpenAI client
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url if config.base_url and config.base_url != "https://api.openai.com/v1" else None,
            timeout=config.timeout,
            max_retries=0  # We handle retries in our resilience layer
        )

        logger.info(
            "OpenAI provider initialized",
            stage="OPENAI.0",
            provider_name=self.name,
            default_model=config.default_model
        )

    async def _stream_internal(
        self,
        query: str,
        model: str,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Internal method to stream responses from OpenAI.

        STAGE-OPENAI.STREAM: Streaming execution

        Args:
            query: The user's input prompt/query.
            model: The specific model identifier (e.g., 'gpt-4').
            thread_id: Unique identifier for request tracing.
            **kwargs: Additional parameters for the OpenAI API (temperature, max_tokens, etc.).

        Yields:
            StreamChunk: Standardized chunks of the generated response.

        Raises:
            ProviderAPIError: For general API errors.
            ProviderAuthenticationError: For invalid API keys.
            RateLimitExceededError: When OpenAI rate limits are hit.
            ProviderNotAvailableError: For connection issues.
        """
        try:
            # Prepare the messages payload
            messages = [{"role": "user", "content": query}]

            # Start the stream
            # We use 'stream=True' to get a generator of chunks
            stream_response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                **kwargs
            )

            # Iterate through the stream of chunks
            async for chunk in stream_response:
                # Extract content from the delta
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content

                    yield StreamChunk(
                        content=content,
                        model=chunk.model,
                        finish_reason=None
                    )

                # Check for finish reason (stop, length, etc.)
                if chunk.choices and chunk.choices[0].finish_reason:
                    yield StreamChunk(
                        content="",
                        model=chunk.model,
                        finish_reason=chunk.choices[0].finish_reason
                    )

        except AuthenticationError as auth_error:
            logger.error(
                "OpenAI authentication failed",
                stage="OPENAI.ERR",
                error=str(auth_error),
                thread_id=thread_id
            )
            raise ProviderAuthenticationError(
                message="Invalid OpenAI API key",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from auth_error

        except RateLimitError as rate_error:
            logger.warning(
                "OpenAI rate limit exceeded",
                stage="OPENAI.ERR",
                error=str(rate_error),
                thread_id=thread_id
            )
            raise RateLimitExceededError(
                message="OpenAI rate limit exceeded",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from rate_error

        except APIConnectionError as conn_error:
            logger.error(
                "OpenAI connection failed",
                stage="OPENAI.ERR",
                error=str(conn_error),
                thread_id=thread_id
            )
            raise ProviderNotAvailableError(
                message="Could not connect to OpenAI",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from conn_error

        except APIError as api_error:
            logger.error(
                "OpenAI API error",
                stage="OPENAI.ERR",
                error=str(api_error),
                thread_id=thread_id
            )
            raise ProviderAPIError(
                message=f"OpenAI API returned an error: {api_error.message}",
                thread_id=thread_id,
                details={"provider": self.name, "code": api_error.code}
            ) from api_error

    def _validate_model(self, model: str) -> None:
        """
        Validate if the requested model is supported by this provider.

        Args:
            model: The model identifier to check.

        Raises:
            ValueError: If the model is not supported/allowed.
        """
        # In a real production app, we might check against a list of allowed models.
        # For now, we allow any string that starts with 'gpt-' or 'o1-'
        if not (model.startswith("gpt-") or model.startswith("o1-")):
            # Log a warning but don't strictly block it to allow for new models
            logger.warning(
                "Potentially unsupported OpenAI model requested",
                stage="OPENAI.VAL",
                model=model
            )

    async def health_check(self) -> dict[str, Any]:
        """
        Perform a health check by making a minimal API call.

        Returns:
            Dict containing the health status and latency.
        """
        try:
            start_time = time.perf_counter()
            # Minimal call to list models (lightweight) or just check connection
            # We'll use a very cheap model request to verify full pipeline
            await self.client.models.list()
            duration_ms = (time.perf_counter() - start_time) * 1000

            return {
                "status": "healthy",
                "latency_ms": round(duration_ms, 2),
                "provider": self.name
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "provider": self.name
            }
