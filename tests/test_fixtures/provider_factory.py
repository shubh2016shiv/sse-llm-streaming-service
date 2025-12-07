"""
Provider Test Factory

Creates controllable provider stubs for testing various scenarios.
"""


from src.llm_stream.providers.base_provider import BaseProvider, StreamChunk


class ProviderTestFactory:
    """Factory for creating test provider stubs."""

    @staticmethod
    def success_provider(
        name: str = "test", chunks: list[StreamChunk] | None = None
    ) -> BaseProvider:
        """Create a provider that successfully streams chunks."""
        if chunks is None:
            chunks = [
                StreamChunk(content="Hello", finish_reason=None),
                StreamChunk(content=" world", finish_reason=None),
                StreamChunk(content="!", finish_reason="stop"),
            ]

        class SuccessProvider(BaseProvider):
            def __init__(self):
                self.name = name
                self._chunks = chunks

            def get_circuit_state(self):
                return "closed"

            async def stream(self, query, model, thread_id):
                for chunk in self._chunks:
                    yield chunk

        return SuccessProvider()

    @staticmethod
    def failing_provider(name: str = "failing", error: Exception = None) -> BaseProvider:
        """Create a provider that always fails."""
        if error is None:
            error = Exception("Provider failure")

        class FailingProvider(BaseProvider):
            def __init__(self):
                self.name = name
                self._error = error

            def get_circuit_state(self):
                return "closed"

            async def stream(self, query, model, thread_id):
                raise self._error

        return FailingProvider()

    @staticmethod
    def circuit_open_provider(name: str = "open-circuit") -> BaseProvider:
        """Create a provider with open circuit breaker."""

        class OpenCircuitProvider(BaseProvider):
            def __init__(self):
                self.name = name

            def get_circuit_state(self):
                return "open"

            async def stream(self, query, model, thread_id):
                # Should not be called due to circuit breaker
                raise Exception("Should not be called")

        return OpenCircuitProvider()

    @staticmethod
    def slow_provider(name: str = "slow", delay: float = 1.0) -> BaseProvider:
        """Create a provider with artificial delays."""
        import asyncio

        class SlowProvider(BaseProvider):
            def __init__(self):
                self.name = name
                self._delay = delay

            def get_circuit_state(self):
                return "closed"

            async def stream(self, query, model, thread_id):
                await asyncio.sleep(self._delay)
                yield StreamChunk(content="Slow response", finish_reason="stop")

        return SlowProvider()

    @staticmethod
    def empty_response_provider(name: str = "empty") -> BaseProvider:
        """Create a provider that returns empty response."""

        class EmptyProvider(BaseProvider):
            def __init__(self):
                self.name = name

            def get_circuit_state(self):
                return "closed"

            async def stream(self, query, model, thread_id):
                yield StreamChunk(content="", finish_reason="stop")

        return EmptyProvider()

    @staticmethod
    def timeout_provider(name: str = "timeout", timeout: float = 30.0) -> BaseProvider:
        """Create a provider that times out."""
        import asyncio

        class TimeoutProvider(BaseProvider):
            def __init__(self):
                self.name = name
                self._timeout = timeout

            def get_circuit_state(self):
                return "closed"

            async def stream(self, query, model, thread_id):
                await asyncio.sleep(self._timeout)
                yield StreamChunk(content="Should not reach here", finish_reason="stop")

        return TimeoutProvider()
