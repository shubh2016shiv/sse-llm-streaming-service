#!/usr/bin/env python3
"""
Google Gemini LLM Provider Implementation

This module implements the Google Gemini provider using the google-generativeai library.
It handles the specific streaming protocol of Gemini and maps it to our standard StreamChunk.

Architectural Decision: Use google-generativeai SDK
- Native support for Gemini features
- Handles authentication via API key
- Efficient streaming implementation

Author: Senior Solution Architect
Date: 2025-12-05
"""

import time
from collections.abc import AsyncGenerator
from typing import Any

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from src.core.exceptions import (
    ProviderAPIError,
    ProviderAuthenticationError,
    ProviderNotAvailableError,
    RateLimitExceededError,
)
from src.core.logging import get_logger
from src.llm_providers.base_provider import BaseProvider, ProviderConfig, StreamChunk

logger = get_logger(__name__)


class GeminiProvider(BaseProvider):
    """
    Concrete implementation of the Google Gemini LLM provider.

    STAGE-GEMINI: Gemini provider operations
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize the Gemini provider.

        Args:
            config: Configuration object.
        """
        super().__init__(config)

        # Configure the global library (it's how the SDK works)
        # Note: In a multi-threaded env, this might be tricky if different keys are used,
        # but typically one key per service instance is fine.
        genai.configure(api_key=config.api_key)

        logger.info(
            "Gemini provider initialized",
            stage="GEMINI.0",
            provider_name=self.name
        )

    async def _stream_internal(
        self,
        query: str,
        model: str,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Internal method to stream responses from Gemini.

        STAGE-GEMINI.STREAM: Streaming execution
        """
        try:
            # Initialize the generative model
            generative_model = genai.GenerativeModel(model)

            # Start the stream
            # The SDK's generate_content_async with stream=True returns an async iterator
            response_stream = await generative_model.generate_content_async(
                query,
                stream=True,
                **kwargs
            )

            async for chunk in response_stream:
                # Gemini chunks contain 'text'
                if chunk.text:
                    yield StreamChunk(
                        content=chunk.text,
                        model=model,
                        finish_reason=None
                    )

            # Send a final empty chunk to signal completion if needed,
            # though the loop ending signals it too.
            yield StreamChunk(
                content="",
                model=model,
                finish_reason="stop"
            )

        except google_exceptions.Unauthenticated as auth_error:
            logger.error("Gemini authentication failed", stage="GEMINI.ERR", error=str(auth_error))
            raise ProviderAuthenticationError(
                message="Invalid Gemini API key",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from auth_error

        except google_exceptions.ResourceExhausted as rate_error:
            logger.warning("Gemini rate limit exceeded", stage="GEMINI.ERR", error=str(rate_error))
            raise RateLimitExceededError(
                message="Gemini rate limit exceeded",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from rate_error

        except google_exceptions.ServiceUnavailable as conn_error:
            logger.error("Gemini service unavailable", stage="GEMINI.ERR", error=str(conn_error))
            raise ProviderNotAvailableError(
                message="Gemini service unavailable",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from conn_error

        except Exception as e:
            # Catch-all for other SDK errors
            logger.error("Gemini API error", stage="GEMINI.ERR", error=str(e))
            raise ProviderAPIError(
                message=f"Gemini API error: {str(e)}",
                thread_id=thread_id,
                details={"provider": self.name}
            ) from e

    def _validate_model(self, model: str) -> None:
        """Validate Gemini model support."""
        if "gemini" not in model.lower():
            logger.warning(
                "Model name does not contain 'gemini', might be incorrect",
                stage="GEMINI.VAL",
                model=model
            )

    async def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        try:
            start_time = time.perf_counter()
            # List models is a good health check
            # Note: list_models returns an iterable, we just need to fetch one to verify auth/conn
            list(genai.list_models(limit=1))
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
