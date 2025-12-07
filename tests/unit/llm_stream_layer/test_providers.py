"""
Unit Tests for LLM Providers

Tests provider implementations, factory selection, and stream chunk processing.
"""


import pytest

from src.llm_stream.providers.base_provider import (
    BaseProvider,
    ProviderConfig,
    ProviderFactory,
    StreamChunk,
)
from src.llm_stream.providers.fake_provider import FakeProvider
from tests.test_fixtures.provider_factory import ProviderTestFactory


@pytest.mark.unit
class TestProviderFactory:
    """Test suite for ProviderFactory."""

    @pytest.fixture
    def factory(self):
        """Create ProviderFactory for testing."""
        return ProviderFactory()

    def test_get_available_providers(self, factory):
        """Test factory returns list of available providers."""
        # Factory starts empty, so we must register providers
        config = ProviderConfig(name="test_openai", api_key="k", base_url="u", default_model="m")
        factory.register("test_openai", FakeProvider, config)

        available = factory.get_available()

        assert isinstance(available, list)
        assert len(available) > 0
        assert "test_openai" in available
        assert isinstance(available[0], str)

    def test_get_provider_by_name(self, factory):
        """Test getting provider by name."""
        # Factory might not have fake registered by default unless we register it
        # or it's in bootstrap
        # Inspecting ProviderFactory code shown earlier: it has empty init.
        # So we probably need to register 'fake' first.
        config = ProviderConfig(name="fake", api_key="k", base_url="u", default_model="m")
        factory.register("fake", FakeProvider, config)

        provider = factory.get("fake")

        assert isinstance(provider, FakeProvider)
        assert provider.name == "fake"

    def test_get_unknown_provider_returns_none(self, factory):
        """Test getting unknown provider raises error."""
        # The code raises ValueError
        with pytest.raises(ValueError):
            factory.get("nonexistent")

    @pytest.mark.asyncio
    async def test_get_healthy_provider_returns_working_provider(self, factory):
        """Test get_healthy_provider returns a working provider."""
        # Need to register at least one provider
        config = ProviderConfig(name="fake", api_key="k", base_url="u", default_model="m")
        factory.register("fake", FakeProvider, config)

        provider = await factory.get_healthy_provider()

        assert provider is not None
        assert hasattr(provider, "stream")
        assert hasattr(provider, "get_circuit_state")

    @pytest.mark.asyncio
    async def test_get_healthy_provider_excludes_specified_providers(self, factory):
        """Test get_healthy_provider respects exclusions."""
        # Register two providers
        config1 = ProviderConfig(name="fake1", api_key="k", base_url="u", default_model="m")
        config2 = ProviderConfig(name="fake2", api_key="k", base_url="u", default_model="m")

        # We need a provider class that can be instantiated with config
        class MockProvider1(FakeProvider):
            pass

        class MockProvider2(FakeProvider):
            pass

        factory.register("fake1", MockProvider1, config1)
        factory.register("fake2", MockProvider2, config2)

        # Get healthy provider excluding the first one
        healthy = await factory.get_healthy_provider(exclude=["fake1"])

        assert healthy is not None
        assert healthy.name == "fake2"


@pytest.mark.unit
class TestFakeProvider:
    """Test suite for FakeProvider."""

    @pytest.fixture
    def fake_provider(self):
        """Create FakeProvider for testing."""
        config = ProviderConfig(name="fake", api_key="k", base_url="u", default_model="m")
        return FakeProvider(config)

    @pytest.mark.asyncio
    async def test_fake_provider_streams_chunks(self, fake_provider):
        """Test FakeProvider streams predefined chunks."""
        chunks = []
        async for chunk in fake_provider.stream("test query", "gpt-3.5-turbo", "test-thread"):
            chunks.append(chunk)

        assert len(chunks) > 0
        assert all(isinstance(chunk, StreamChunk) for chunk in chunks)
        assert all(chunk.content for chunk in chunks[:-1])  # All but last have content

        # FakeProvider logic: finish_reason="stop" is on the last chunk
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_fake_provider_handles_different_models(self, fake_provider):
        """Test FakeProvider works with different model names."""
        models = ["gpt-3.5-turbo", "gpt-4", "claude-3"]

        for model in models:
            chunks = []
            async for chunk in fake_provider.stream("test", model, "thread"):
                chunks.append(chunk)
            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_fake_provider_circuit_state_closed_by_default(self, fake_provider):
        """Test FakeProvider has closed circuit by default."""
        # base_provider.get_circuit_state is async
        assert await fake_provider.get_circuit_state() == "closed"


@pytest.mark.unit
class TestBaseProviderInterface:
    """Test base provider interface contract."""

    def test_base_provider_is_abstract(self):
        """Test BaseProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            # We need to mock minimal args if we were to try, but abstract class
            # check avoids even looking at init often
            # But BaseProvider has __init__.
            # Abstract checks happen at instantiation.
            BaseProvider(ProviderConfig(name="x", api_key="y", base_url="z"))

    def test_base_provider_defines_required_methods(self):
        """Test BaseProvider defines required interface methods."""
        # Check that required methods exist
        assert hasattr(BaseProvider, "stream")
        assert hasattr(BaseProvider, "get_circuit_state")

        # Check method signatures (basic check)
        import inspect

        stream_sig = inspect.signature(BaseProvider.stream)

        assert "query" in stream_sig.parameters
        assert "model" in stream_sig.parameters
        assert "thread_id" in stream_sig.parameters


@pytest.mark.unit
class TestProviderTestFactory:
    """Test suite for ProviderTestFactory helper."""

    @pytest.mark.asyncio
    async def test_success_provider_creation(self):
        """Test creating a success provider."""
        provider = ProviderTestFactory.success_provider()

        assert await provider.get_circuit_state() == "closed"
        assert provider.name == "test"

    @pytest.mark.asyncio
    async def test_success_provider_streams_correctly(self):
        """Test success provider streams expected chunks."""
        provider = ProviderTestFactory.success_provider()

        chunks = []
        async for chunk in provider.stream("query", "model", "thread"):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].content == "!"
        assert chunks[2].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_failing_provider_creation(self):
        """Test creating a failing provider."""
        provider = ProviderTestFactory.failing_provider()

        assert await provider.get_circuit_state() == "closed"

    @pytest.mark.asyncio
    async def test_failing_provider_raises_exception(self):
        """Test failing provider raises expected exception."""
        error = RuntimeError("Test failure")
        provider = ProviderTestFactory.failing_provider(error=error)

        with pytest.raises(RuntimeError) as exc_info:
            async for _ in provider.stream("query", "model", "thread"):
                pass

        assert str(exc_info.value) == "Test failure"

    @pytest.mark.asyncio
    async def test_circuit_open_provider_creation(self):
        """Test creating a provider with open circuit."""
        provider = ProviderTestFactory.circuit_open_provider()

        assert await provider.get_circuit_state() == "open"

    @pytest.mark.asyncio
    async def test_circuit_open_provider_blocks_streaming(self):
        """Test circuit open provider prevents streaming."""
        provider = ProviderTestFactory.circuit_open_provider()

        # Should not yield any chunks due to circuit breaker check
        chunks = []
        try:
             async for chunk in provider.stream("query", "model", "thread"):
                chunks.append(chunk)
        except Exception:
             # Circuit breaker or internal logic might raise
             pass

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_slow_provider_creation(self):
        """Test creating a slow provider."""
        provider = ProviderTestFactory.slow_provider(delay=2.0)

        assert await provider.get_circuit_state() == "closed"

    @pytest.mark.asyncio
    async def test_slow_provider_has_delay(self):
        """Test slow provider introduces expected delay."""
        import time

        provider = ProviderTestFactory.slow_provider(delay=0.1)

        start_time = time.time()
        chunks = []
        async for chunk in provider.stream("query", "model", "thread"):
            chunks.append(chunk)
        end_time = time.time()

        assert end_time - start_time >= 0.1
        assert len(chunks) == 1
        assert chunks[0].content == "Slow response"

    @pytest.mark.asyncio
    async def test_empty_response_provider_creation(self):
        """Test creating a provider with empty response."""
        provider = ProviderTestFactory.empty_response_provider()

        assert await provider.get_circuit_state() == "closed"

    @pytest.mark.asyncio
    async def test_empty_response_provider_streams_empty(self):
        """Test empty response provider streams empty content."""
        provider = ProviderTestFactory.empty_response_provider()

        chunks = []
        async for chunk in provider.stream("query", "model", "thread"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content == ""
        assert chunks[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_timeout_provider_creation(self):
        """Test creating a timeout provider."""
        provider = ProviderTestFactory.timeout_provider()

        assert await provider.get_circuit_state() == "closed"

    @pytest.mark.asyncio
    async def test_timeout_provider_times_out(self):
        """Test timeout provider exceeds time limit."""
        import asyncio

        provider = ProviderTestFactory.timeout_provider(timeout=0.1)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                provider.stream("query", "model", "thread").__aiter__().__anext__(), timeout=0.05
            )


@pytest.mark.unit
class TestStreamChunk:
    """Test suite for StreamChunk data structure."""

    def test_stream_chunk_creation(self):
        """Test StreamChunk can be created."""
        chunk = StreamChunk(content="test", finish_reason=None)

        assert chunk.content == "test"
        assert chunk.finish_reason is None

    def test_stream_chunk_with_finish_reason(self):
        """Test StreamChunk with finish reason."""
        chunk = StreamChunk(content="final", finish_reason="stop")

        assert chunk.content == "final"
        assert chunk.finish_reason == "stop"

    def test_stream_chunk_equality(self):
        """Test StreamChunk equality comparison."""
        chunk1 = StreamChunk(content="test", finish_reason="stop")
        chunk2 = StreamChunk(content="test", finish_reason="stop")
        chunk3 = StreamChunk(content="different", finish_reason="stop")

        assert chunk1 == chunk2
        assert chunk1 != chunk3

    def test_stream_chunk_string_representation(self):
        """Test StreamChunk string representation."""
        chunk = StreamChunk(content="Hello", finish_reason=None)

        str_repr = str(chunk)
        assert "Hello" in str_repr
        assert "finish_reason=None" in str_repr


@pytest.mark.unit
class TestProviderCircuitBreakerIntegration:
    """Test provider circuit breaker state handling."""

    @pytest.mark.asyncio
    async def test_provider_circuit_state_changes(self):
        """Test provider circuit state can be changed."""
        provider = ProviderTestFactory.success_provider()

        # Initially closed
        assert await provider.get_circuit_state() == "closed"

        # Simulate circuit opening (would be done by circuit breaker)
        # This tests the interface - actual state managed by circuit breaker
        provider._circuit_state = "open"
        assert await provider.get_circuit_state() == "open"

        provider._circuit_state = "half_open"
        assert await provider.get_circuit_state() == "half_open"

        provider._circuit_state = "closed"
        assert await provider.get_circuit_state() == "closed"

    @pytest.mark.asyncio
    async def test_invalid_circuit_state_handling(self):
        """Test handling of invalid circuit states."""
        provider = ProviderTestFactory.success_provider()

        # Set invalid state
        provider._circuit_state = "invalid"

        # Should still return the state
        assert await provider.get_circuit_state() == "invalid"
