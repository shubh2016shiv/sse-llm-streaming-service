"""
Pytest Configuration and Shared Test Fixtures

This module provides pytest configuration and reusable fixtures for all tests.
All fixtures defined here are automatically available to all test files.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ============================================================================
# Pytest Configuration
# ============================================================================

# pytest-asyncio is automatically loaded via pyproject.toml configuration
# event_loop fixture removed to let pytest-asyncio handle it automatically


# ============================================================================
# Mock Configuration Fixtures
# ============================================================================


@pytest.fixture
def mock_settings():
    """
    Mock application settings for testing.

    Returns a MagicMock with common settings attributes.
    """
    from src.core.config.settings import Settings

    settings = MagicMock(spec=Settings)

    # Cache settings
    settings.cache.CACHE_L1_MAX_SIZE = 1000
    settings.cache.CACHE_RESPONSE_TTL = 3600
    settings.cache.ENABLE_CACHING = True

    # Settings root level
    settings.ENABLE_CACHING = True

    # App settings
    settings.app.ENVIRONMENT = "test"
    settings.app.APP_VERSION = "1.0.0-test"
    settings.app.APP_NAME = "SSE Test"

    # Execution tracking settings
    settings.EXECUTION_TRACKING_SAMPLE_RATE = 0.1

    # Circuit breaker settings - MUST be actual integers for pybreaker comparison
    settings.circuit_breaker.CB_FAILURE_THRESHOLD = 5
    settings.circuit_breaker.CB_RECOVERY_TIMEOUT = 60

    return settings


# ============================================================================
# Environment-Based Integration Toggles
# ============================================================================


@pytest.fixture(scope="session")
def use_real_redis():
    """Check if real Redis should be used for integration tests."""
    import os

    return os.getenv("USE_REAL_REDIS", "0").lower() in ("1", "true", "yes")


@pytest.fixture(scope="session")
def use_real_providers():
    """Check if real provider APIs should be used for integration tests."""
    import os

    return os.getenv("USE_REAL_PROVIDERS", "0").lower() in ("1", "true", "yes")


# ============================================================================
# Mock Infrastructure Fixtures
# ============================================================================


@pytest.fixture
def mock_cache_manager():
    """
    Mock CacheManager for isolated testing.

    Provides async mock methods for get/set operations.
    """
    from src.infrastructure.cache.cache_manager import CacheManager

    cache = AsyncMock(spec=CacheManager)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    cache.stats = MagicMock(
        return_value={"l1_hits": 0, "l1_misses": 0, "l2_hits": 0, "l2_misses": 0}
    )
    cache.health_check = AsyncMock(return_value={"status": "healthy"})

    return cache


@pytest.fixture
def in_memory_redis_client():
    """
    In-memory Redis client stub for testing.

    Mimics Redis operations using in-memory storage.
    """

    class InMemoryRedis:
        def __init__(self):
            self.data = {}
            self.ttl_data = {}  # key -> expiration timestamp

        async def connect(self):
            pass

        async def get(self, key):
            # Check TTL
            if key in self.ttl_data:
                if asyncio.get_event_loop().time() > self.ttl_data[key]:
                    await self.delete(key)
                    return None
            return self.data.get(key)

        async def set(self, key, value, ttl=None):
            self.data[key] = value
            if ttl:
                self.ttl_data[key] = asyncio.get_event_loop().time() + ttl
            elif key in self.ttl_data:
                del self.ttl_data[key]

        async def delete(self, key):
            if key in self.data:
                del self.data[key]
            if key in self.ttl_data:
                del self.ttl_data[key]

        async def incr(self, key):
            value = int(await self.get(key) or 0) + 1
            await self.set(key, str(value))
            return value

        async def health_check(self):
            return {"status": "healthy", "type": "in_memory"}

        def get_pipeline_manager(self):
            # Simple pipeline stub that doesn't batch
            class FakePipeline:
                async def execute_command(self, cmd, *args):
                    if cmd == "get":
                        return self.data.get(args[0])
                    return None

            return FakePipeline()

    return InMemoryRedis()


@pytest.fixture
async def real_or_mock_redis(use_real_redis, in_memory_redis_client):
    """
    Return real Redis client if enabled, otherwise in-memory stub.
    """
    if use_real_redis:
        from src.infrastructure.cache.redis_client import get_redis_client

        client = get_redis_client()
        await client.connect()
        return client
    return in_memory_redis_client


@pytest.fixture
def mock_execution_tracker():
    """
    Mock ExecutionTracker for testing.

    Provides context manager for stage tracking.
    """
    from src.core.observability.execution_tracker import ExecutionTracker

    tracker = MagicMock(spec=ExecutionTracker)

    # Mock context manager for track_stage
    tracker.track_stage = MagicMock()
    tracker.track_stage.return_value.__enter__ = MagicMock()
    # Return None from __exit__ so exceptions are NOT swallowed
    tracker.track_stage.return_value.__exit__ = MagicMock(return_value=None)

    tracker.get_execution_summary = MagicMock(return_value={"total_duration_ms": 100, "stages": []})
    tracker.clear_thread_data = MagicMock()
    tracker.should_track = MagicMock(return_value=True)

    return tracker


@pytest.fixture
def mock_provider_factory():
    """
    Mock ProviderFactory for testing provider selection.

    Returns a factory with a mock provider.
    """
    from src.llm_stream.providers.base_provider import BaseProvider, ProviderFactory

    factory = MagicMock(spec=ProviderFactory)

    # Create mock provider
    mock_provider = AsyncMock(spec=BaseProvider)
    mock_provider.name = "test-provider"
    mock_provider.get_circuit_state = MagicMock(return_value="closed")
    mock_provider.stream = AsyncMock()

    factory.get = MagicMock(return_value=mock_provider)
    factory.get_healthy_provider = AsyncMock(return_value=mock_provider)
    factory.get_available = MagicMock(return_value=["test-provider"])

    return factory


@pytest.fixture
def fake_provider_factory():
    """
    Fake provider factory that creates controllable provider stubs.
    """
    from src.llm_stream.providers.base_provider import BaseProvider, ProviderFactory

    class FakeProvider(BaseProvider):
        def __init__(self, name="fake", chunks=None, should_fail=False, circuit_state="closed"):
            self.name = name
            self._chunks = chunks or []
            self._should_fail = should_fail
            self._circuit_state = circuit_state

        def get_circuit_state(self):
            return self._circuit_state

        async def stream(self, query, model, thread_id):
            if self._should_fail:
                raise Exception("Fake provider failure")
            for chunk in self._chunks:
                yield chunk

    class FakeProviderFactory(ProviderFactory):
        def __init__(self, providers=None):
            self._providers = providers or {}

        def get(self, name):
            return self._providers.get(name, FakeProvider(name))

        def get_healthy_provider(self, exclude=None):
            exclude = exclude or []
            for name, provider in self._providers.items():
                if name not in exclude and provider.get_circuit_state() != "open":
                    return provider
            return FakeProvider("fallback")

        def get_available(self):
            return list(self._providers.keys())

    return FakeProviderFactory


@pytest.fixture
def mock_request_validator():
    """
    Mock RequestValidator for testing validation logic.
    """
    from src.application.validators import RequestValidator

    validator = MagicMock(spec=RequestValidator)
    validator.validate_query = MagicMock()
    validator.validate_model = MagicMock()
    validator.check_connection_limit = MagicMock()

    return validator


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_stream_request():
    """
    Sample StreamRequest for testing.

    Provides a valid request object with typical values.
    """
    from src.llm_stream.models.stream_request import StreamRequest

    return StreamRequest(
        query="What is the capital of France?",
        model="gpt-3.5-turbo",
        provider="openai",
        thread_id="test-thread-123",
        user_id="test-user-456",
    )


@pytest.fixture
def sample_stream_chunks():
    """
    Sample StreamChunk list for testing streaming.

    Returns a list of chunks simulating a typical LLM response.
    """
    from src.llm_stream.providers.base_provider import StreamChunk

    return [
        StreamChunk(content="The", finish_reason=None),
        StreamChunk(content=" capital", finish_reason=None),
        StreamChunk(content=" of", finish_reason=None),
        StreamChunk(content=" France", finish_reason=None),
        StreamChunk(content=" is", finish_reason=None),
        StreamChunk(content=" Paris", finish_reason="stop"),
    ]


@pytest.fixture
def empty_stream_chunks():
    """Empty chunk list for testing edge cases."""
    return []


@pytest.fixture
def error_stream_chunks():
    """Chunks that include an error scenario."""
    from src.llm_stream.providers.base_provider import StreamChunk

    return [
        StreamChunk(content="This", finish_reason=None),
        StreamChunk(content=" will", finish_reason=None),
        # Simulate early termination
    ]


@pytest.fixture
def sample_stream_request_with_user():
    """Sample request with user ID for testing user-specific logic."""
    from src.llm_stream.models.stream_request import StreamRequest

    return StreamRequest(
        query="What is the capital of Germany?",
        model="gpt-4",
        provider="openai",
        thread_id="thread-user-123",
        user_id="user-456",
    )


@pytest.fixture
def invalid_stream_request():
    """Invalid request for testing validation failures."""
    from src.llm_stream.models.stream_request import StreamRequest

    return StreamRequest(
        query="",  # Empty query
        model="invalid-model",
        provider="openai",
        thread_id="thread-123",
        user_id="user-456",
    )


# ============================================================================
# Async Infrastructure Fixtures
# ============================================================================


@pytest.fixture(scope="function")
async def cache_manager(mock_settings):
    """Create CacheManager with mocked dependencies."""
    from unittest.mock import AsyncMock, patch

    from src.infrastructure.cache.cache_manager import CacheManager

    with (
        patch("src.infrastructure.cache.cache_manager.get_settings", return_value=mock_settings),
        patch("src.infrastructure.cache.cache_manager.get_tracker"),
        patch("src.infrastructure.cache.cache_manager.get_redis_client") as mock_get_redis,
    ):
        manager = CacheManager()

        # Setup Redis mock
        mock_redis = AsyncMock()
        mock_redis.connect = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.health_check = AsyncMock(return_value={"status": "healthy"})
        # Return None to test fallback
        mock_redis.get_pipeline_manager = AsyncMock(return_value=None)
        mock_get_redis.return_value = mock_redis

        # Initialize
        await manager.initialize()

        return manager


@pytest.fixture(scope="function")
async def cb_manager(mock_settings):
    """Create CircuitBreakerManager with mocked dependencies."""
    from unittest.mock import AsyncMock, patch

    from src.core.resilience.circuit_breaker import CircuitBreakerManager

    with patch("src.core.resilience.circuit_breaker.get_settings", return_value=mock_settings):
        manager = CircuitBreakerManager()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Default state none
        mock_redis.set = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)

        await manager.initialize(mock_redis)
        return manager


# ============================================================================
# Test Utility Fixtures
# ============================================================================


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis_client():
    """Generic mock Redis client for testing."""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=True)
    client.incr = AsyncMock(return_value=1)
    client.health_check = AsyncMock(return_value={"status": "healthy"})
    return client


@pytest.fixture
def mock_health_checker():
    """Mock health checker for infrastructure testing."""
    from src.infrastructure.monitoring.health_checker import HealthChecker

    checker = AsyncMock(spec=HealthChecker)
    checker.check_redis = AsyncMock(return_value={"status": "healthy", "latency_ms": 1.0})
    checker.check_overall = AsyncMock(return_value={"status": "healthy", "checks": {}})
    return checker


@pytest.fixture
def mock_metrics_collector():
    """Mock metrics collector for monitoring testing."""
    from src.infrastructure.monitoring.metrics_collector import MetricsCollector

    collector = AsyncMock(spec=MetricsCollector)
    collector.increment_counter = MagicMock()
    collector.record_histogram = MagicMock()
    collector.get_metrics = MagicMock(return_value={})
    return collector
