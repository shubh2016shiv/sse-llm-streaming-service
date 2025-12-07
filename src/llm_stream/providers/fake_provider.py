import asyncio
import random
import time
from collections.abc import AsyncGenerator
from typing import Any

from src.core.logging import get_logger
from src.llm_stream.providers.base_provider import BaseProvider, ProviderConfig, StreamChunk

logger = get_logger(__name__)

class FakeProvider(BaseProvider):
    """
    A fake LLM provider for testing and demonstration purposes.
    Simulates token generation with configurable latency and realistic streaming behavior.
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        # Simulation settings
        self.min_latency = 0.05  # Minimum time between chunks
        self.max_latency = 0.15  # Maximum time between chunks
        self.chars_per_chunk = 4 # Average characters per chunk (token simulation)
        self.failure_rate = 0.0  # Simulated failure rate (0.0 to 1.0)

    async def _stream_internal(
        self,
        query: str,
        model: str,
        thread_id: str | None = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Simulate streaming response generation.
        """
        # Simulate initial processing delay (TTFT - Time To First Token)
        await asyncio.sleep(random.uniform(0.2, 0.8))

        # Determine response logic based on query for "realism"
        response_text = self._generate_response_content(query)

        # Simulate streaming
        chunks = self._chunk_text(response_text)

        for i, chunk_text in enumerate(chunks):
            # Simulate network/processing latency
            await asyncio.sleep(random.uniform(self.min_latency, self.max_latency))

            # Simulate occasional random failures if configured
            if self.failure_rate > 0 and random.random() < self.failure_rate:
                raise Exception("Simulated provider failure")

            finish_reason = "stop" if i == len(chunks) - 1 else None

            yield StreamChunk(
                content=chunk_text,
                finish_reason=finish_reason,
                model=model,
                timestamp=time.time()
            )

    def _validate_model(self, model: str) -> None:
        """Accepts any model name for testing."""
        # No-op validation
        pass

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "latency_ms": 5,
            "provider": "fake"
        }

    def _generate_response_content(self, query: str) -> str:
        """Generates a dummy response based on the query."""
        lorem_ipsum = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
            "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris "
            "nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in "
            "reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
            "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
            "officia deserunt mollit anim id est laborum."
        )

        # Make the response length somewhat related to the query length for variance
        multiplier = (len(query) % 3) + 1
        return f"Rank {multiplier} Response: " + (lorem_ipsum * multiplier)

    def _chunk_text(self, text: str) -> list[str]:
        """Splits text into small chunks to simulate tokens."""
        chunks = []
        i = 0
        while i < len(text):
            # Randomize chunk size to simulate variable token lengths
            chunk_size = random.randint(2, 6)
            chunks.append(text[i : i + chunk_size])
            i += chunk_size
        return chunks
