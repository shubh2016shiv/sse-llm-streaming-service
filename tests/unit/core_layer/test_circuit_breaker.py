"""
Unit Tests for CircuitBreaker (Custom Implementation)

Tests the resilience logic including state transitions (closed -> open -> half-open),
failure counting, and distributed state coordination via Redis.
"""

from unittest.mock import AsyncMock

import pytest

from src.core.resilience.circuit_breaker import (
    CircuitBreakerManager,
    CircuitBreakerOpenError,
    CircuitState,
    DistributedCircuitBreaker,
    ResilientCall,
)


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    # Default behavior for gets is None (empty) or 0 (counter)
    mock.get.return_value = None
    mock.incr.return_value = 1
    return mock


@pytest.fixture
def cb_manager(mock_redis):
    manager = CircuitBreakerManager()
    # We can't await in fixture easily without pytest-asyncio magic,
    # but we can set the internal var directly for unit testing
    manager._redis = mock_redis
    manager._breakers = {}  # Reset
    return manager


@pytest.mark.unit
class TestCircuitBreakerManager:
    @pytest.mark.asyncio
    async def test_get_breaker_creates_new_instance(self, cb_manager):
        name = "test-provider"
        breaker = cb_manager.get_breaker(name)
        assert isinstance(breaker, DistributedCircuitBreaker)
        assert breaker.name == name
        assert name in cb_manager._breakers

    @pytest.mark.asyncio
    async def test_get_breaker_returns_existing_instance(self, cb_manager):
        name = "test-provider"
        breaker1 = cb_manager.get_breaker(name)
        breaker2 = cb_manager.get_breaker(name)
        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_breaker_initial_state_closed(self, cb_manager):
        breaker = cb_manager.get_breaker("new-provider")
        # Mock redis returning None -> Closed
        cb_manager._redis.get.return_value = None
        state = await breaker.get_state()
        assert state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_record_failure_increments_count(self, cb_manager):
        name = "fail-provider"
        breaker = cb_manager.get_breaker(name)

        # Test 1 failure
        cb_manager._redis.incr.return_value = 1
        await breaker.record_failure()

        cb_manager._redis.incr.assert_called_with(f"circuit:{name}:failures")
        # Should not set state yet
        cb_manager._redis.set.assert_called()  # It sets last failure time, but not state key yet

        # Verify state key set ONLY if threshold reached
        # If threshold is 5, let's say we hit 5
        cb_manager._redis.incr.return_value = 5
        await breaker.record_failure()
        # Now it should set state to OPEN
        call_args_list = cb_manager._redis.set.call_args_list
        # Check if one of the calls was setting state to open
        state_key = f"circuit:{name}:state"
        found = False
        for args, _ in call_args_list:
            if args[0] == state_key and args[1] == "open":
                found = True
        assert found, "Should have set state to OPEN after max failures"

    @pytest.mark.asyncio
    async def test_should_allow_request_logic(self, cb_manager):
        breaker = cb_manager.get_breaker("logic-test")

        # Case 1: Closed
        cb_manager._redis.get.side_effect = lambda k: "closed" if "state" in k else None
        assert await breaker.should_allow_request() is True

        # Case 2: Open, NO timeout passed
        cb_manager._redis.get.side_effect = (
            lambda k: "open" if "state" in k else "9999999999.9"
        )  # Future time
        assert await breaker.should_allow_request() is False

        # Case 3: Open, Timeout PASSED (Half-Open logic)
        import time

        past_time = time.time() - 1000  # Long ago
        cb_manager._redis.get.side_effect = lambda k: "open" if "state" in k else str(past_time)
        assert await breaker.should_allow_request() is True

    @pytest.mark.asyncio
    async def test_record_success_resets_everything(self, cb_manager):
        breaker = cb_manager.get_breaker("success-test")

        # Determine we are currently open
        cb_manager._redis.get.return_value = "open"

        await breaker.record_success()

        # Should set state to closed
        cb_manager._redis.set.assert_any_call(f"circuit:{breaker.name}:state", "closed")
        # Should set failures to 0
        cb_manager._redis.set.assert_any_call(f"circuit:{breaker.name}:failures", 0)


@pytest.mark.unit
class TestResilientCall:
    @pytest.mark.asyncio
    async def test_call_fails_fast_when_circuit_open(self, cb_manager):
        # Setup: Circuit is strictly OPEN and timeout hasn't passed
        resilient = ResilientCall("open-provider", redis_client=cb_manager._redis)

        # Mock breaker to deny request
        resilient.breaker.should_allow_request = AsyncMock(return_value=False)

        async def target():
            return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await resilient.call(target)

        # Target should NOT be called

    @pytest.mark.asyncio
    async def test_call_retries_transient_failures(self, cb_manager):
        resilient = ResilientCall("retry-provider", redis_client=cb_manager._redis, max_retries=3)

        # Mock allow request
        resilient.breaker.should_allow_request = AsyncMock(return_value=True)
        resilient.breaker.record_success = AsyncMock()
        resilient.breaker.record_failure = AsyncMock()

        attempts = 0

        async def flaky_target():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("Blip")
            return "Success"

        result = await resilient.call(flaky_target)
        assert result == "Success"
        assert attempts == 3
        # Should record success at end
        resilient.breaker.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_trips_after_persistent_failure(self, cb_manager):
        resilient = ResilientCall("dead-provider", redis_client=cb_manager._redis, max_retries=1)

        resilient.breaker.should_allow_request = AsyncMock(return_value=True)
        resilient.breaker.record_failure = AsyncMock()

        async def bad_target():
            raise ConnectionError("Dead")

        with pytest.raises(ConnectionError):
            await resilient.call(bad_target)

        # Should have recorded failure
        resilient.breaker.record_failure.assert_called_once()
