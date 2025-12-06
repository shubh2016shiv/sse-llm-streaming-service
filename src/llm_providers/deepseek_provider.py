#!/usr/bin/env python3
"""
DeepSeek LLM Provider Implementation

This module implements the DeepSeek provider. DeepSeek's API is OpenAI-compatible,
so we leverage the AsyncOpenAI client but configured for DeepSeek's endpoints.
We maintain a separate class to ensure clear separation of concerns and allow for
future divergence or specific handling.

Architectural Decision: Separate class for DeepSeek
- Explicit configuration and logging
- Independent circuit breaker state
- Clearer monitoring separation

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


class DeepSeekProvider(BaseProvider):
    """
    Concrete implementation of the DeepSeek LLM provider.

    STAGE-DEEPSEEK: DeepSeek provider operations

    Uses the OpenAI SDK with DeepSeek's base URL.
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize the DeepSeek provider.

        Args:
            config: Configuration object.
        """
        super().__init__(config)

        # DeepSeek uses OpenAI-compatible API
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,  # e.g., "https://api.deepseek.com/v1"
            timeout=config.timeout,
            max_retries=0
        )

        logger.info(
            "DeepSeek provider initialized",
            stage="DEEPSEEK.0",
            provider_name=self.name,
            base_url=config.base_url
        )

    async def _stream_internal(
        self,
        query: str,
        model: str,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Internal method to stream responses from DeepSeek.

        STAGE-DEEPSEEK.STREAM: Streaming execution
        """
        try:
            messages = [{"role": "user", "content": query}]

            stream_response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                **kwargs
            )

            async for chunk in stream_response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield StreamChunk(
                        content=content,
                        model=chunk.model,
                        finish_reason=None
                    )

                if chunk.choices and chunk.choices[0].finish_reason:
                    yield StreamChunk(
                        content="",
                        model=chunk.model,
                        finish_reason=chunk.choices[0].finish_reason
                    )

        except AuthenticationError as auth_error:
            logger.error(
                "DeepSeek authentication failed",
                stage="DEEPSEEK.ERR",
                error=str(auth_error),
            )
            raise ProviderAuthenticationError(
                message="Invalid DeepSeek API key",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from auth_error

        except RateLimitError as rate_error:
            logger.warning(
                "DeepSeek rate limit exceeded",
                stage="DEEPSEEK.ERR",
                error=str(rate_error),
            )
            raise RateLimitExceededError(
                message="DeepSeek rate limit exceeded",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from rate_error

        except APIConnectionError as conn_error:
            logger.error(
                "DeepSeek connection failed",
                stage="DEEPSEEK.ERR",
                error=str(conn_error),
            )
            raise ProviderNotAvailableError(
                message="Could not connect to DeepSeek",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from conn_error

        except APIError as api_error:
            logger.error(
                "DeepSeek API error",
                stage="DEEPSEEK.ERR",
                error=str(api_error),
            )
            raise ProviderAPIError(
                message=f"DeepSeek API error: {api_error.message}",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from api_error

    def _validate_model(self, model: str) -> None:
        """Validate DeepSeek model support."""
        if "deepseek" not in model.lower():
            logger.warning(
                "Model name does not contain 'deepseek', might be incorrect",
                stage="DEEPSEEK.VAL",
                model=model
            )

    async def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        try:
            start_time = time.perf_counter()
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
