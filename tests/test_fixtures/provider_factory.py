"""
Provider Test Factory

Creates controllable provider stubs for testing various scenarios.
"""


from src.llm_stream.providers.base_provider import BaseProvider, ProviderConfig, StreamChunk


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
                # Create minimal config for test provider
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._chunks = chunks
                self._circuit_state = "closed"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                for chunk in self._chunks:
                    yield chunk

            def _validate_model(self, model: str) -> None:
                # Accept any model for testing
                pass

            async def health_check(self):
                return {"status": "healthy", "provider": self.name}

        return SuccessProvider()

    @staticmethod
    def failing_provider(name: str = "failing", error: Exception = None) -> BaseProvider:
        """Create a provider that always fails."""
        if error is None:
            error = Exception("Provider failure")

        class FailingProvider(BaseProvider):
            def __init__(self):
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._error = error
                self._circuit_state = "closed"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                raise self._error
                yield  # Make it a generator

            def _validate_model(self, model: str) -> None:
                pass

            async def health_check(self):
                return {"status": "unhealthy", "provider": self.name}

        return FailingProvider()

    @staticmethod
    def circuit_open_provider(name: str = "open-circuit") -> BaseProvider:
        """Create a provider with open circuit breaker."""

        class OpenCircuitProvider(BaseProvider):
            def __init__(self):
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._circuit_state = "open"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                # Should not be called due to circuit breaker
                raise Exception("Should not be called")
                yield  # Make it a generator

            def _validate_model(self, model: str) -> None:
                pass

            async def health_check(self):
                return {"status": "circuit_open", "provider": self.name}

        return OpenCircuitProvider()

    @staticmethod
    def slow_provider(name: str = "slow", delay: float = 1.0) -> BaseProvider:
        """Create a provider with artificial delays."""
        import asyncio

        class SlowProvider(BaseProvider):
            def __init__(self):
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._delay = delay
                self._circuit_state = "closed"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                await asyncio.sleep(self._delay)
                yield StreamChunk(content="Slow response", finish_reason="stop")

            def _validate_model(self, model: str) -> None:
                pass

            async def health_check(self):
                return {"status": "healthy", "provider": self.name}

        return SlowProvider()

    @staticmethod
    def empty_response_provider(name: str = "empty") -> BaseProvider:
        """Create a provider that returns empty response."""

        class EmptyProvider(BaseProvider):
            def __init__(self):
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._circuit_state = "closed"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                yield StreamChunk(content="", finish_reason="stop")

            def _validate_model(self, model: str) -> None:
                pass

            async def health_check(self):
                return {"status": "healthy", "provider": self.name}

        return EmptyProvider()

    @staticmethod
    def timeout_provider(name: str = "timeout", timeout: float = 30.0) -> BaseProvider:
        """Create a provider that times out."""
        import asyncio

        class TimeoutProvider(BaseProvider):
            def __init__(self):
                config = ProviderConfig(
                    name=name,
                    api_key="test-key",
                    base_url="http://test",
                    default_model="test-model"
                )
                super().__init__(config)
                self._timeout = timeout
                self._circuit_state = "closed"

            async def get_circuit_state(self):
                return self._circuit_state

            async def _stream_internal(self, query, model, thread_id=None, **kwargs):
                await asyncio.sleep(self._timeout)
                yield StreamChunk(content="Should not reach here", finish_reason="stop")

            def _validate_model(self, model: str) -> None:
                pass

            async def health_check(self):
                return {"status": "healthy", "provider": self.name}

        return TimeoutProvider()
