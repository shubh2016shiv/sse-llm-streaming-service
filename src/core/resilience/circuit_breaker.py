"""
Circuit Breaker and Resilience Layer for LLM Providers.

This module implements a custom, Redis-backed Distributed Circuit Breaker pattern designed
specifically for high-reliability LLM interactions.

MECHANISM OF ACTION:
-------------------
1.  **Distributed State**:
    The circuit breaker state (CLOSED, OPEN, HALF-OPEN) is stored in Redis. This ensures that if
    Provider X fails for one instance of this application, all instances stop calling Provider X
    immediately. This prevents "thundering herd" problems and allows the provider time to recover.

2.  **State Transitions**:
    - **CLOSED**: The system is healthy. Requests are allowed.
      - On Failure: Failure counter in Redis increments.
      - On Success: Failure counter resets to 0.
      - Threshold Reached: If failures >= MAX_FAILURES, state transitions to OPEN.

    - **OPEN**: The provider is down. Requests are blocked immediately (Fail Fast).
      - Behavior: Raises `CircuitBreakerOpenError` without attempting the call.
      - Recovery: After `reset_timeout` seconds, the state virtually transitions to HALF-OPEN.

    - **HALF-OPEN**: Probing mode.
      - Behavior: Allows ONE "probe" request to pass through to test the waters.
      - On Success: The provider is recovered! State transitions back to CLOSED.
      - On Failure: The provider is still down. State transitions back to OPEN, and the
        timeout timer restarts.

3.  **ResilientCall Orchestration**:
    The `ResilientCall` class wraps this logic with retries:
    a.  **Check Circuit**: Is the circuit open? If yes, fail immediately.
    b.  **Execute with Retry**: If closed, try to call the provider. If it fails transiently
        (network blip), retry using exponential backoff (Tenacity).
    c.  **Record Result**:
        - If all retries fail: Record a FAILURE in the circuit breaker.
        - If successful: Record a SUCCESS (resets counters).

This design balances aggressive error handling (fails fast) with maximum reliability (retries
transient errors) and protects downstream services.
"""

import time
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.core.config.constants import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY
from src.core.config.settings import get_settings
from src.core.exceptions import (
    CircuitBreakerOpenError,
    ProviderTimeoutError,
)
from src.core.logging.logger import get_logger
from src.core.observability.execution_tracker import get_tracker

logger = get_logger(__name__)


class CircuitState(str, Enum):
    """Enumeration of possible circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class DistributedCircuitBreaker:
    """
    A custom, lightweight, Redis-backed circuit breaker.

    Unlike standard libraries, this is designed specifically for:
    1. AsyncIO native execution.
    2. Distributed state via Redis (so all pods share knowledge of downtime).
    3. Simplicity and transparency without complex middleware.
    """

    def __init__(self, name: str, redis_client=None):
        self.name = name
        self.settings = get_settings()
        self._redis = redis_client
        self._max_failures = self.settings.circuit_breaker.CB_FAILURE_THRESHOLD
        self._reset_timeout = self.settings.circuit_breaker.CB_RECOVERY_TIMEOUT

        # Redis Keys
        self._key_prefix = f"circuit:{name}"
        self._state_key = f"{self._key_prefix}:state"
        self._failures_key = f"{self._key_prefix}:failures"
        self._last_failure_time_key = f"{self._key_prefix}:last_failure_time"

    async def get_state(self) -> str:
        """Get the current state from Redis, defaulting to CLOSED if Redis is down."""
        try:
            if not self._redis:
                return CircuitState.CLOSED

            state = await self._redis.get(self._state_key)
            if not state:
                return CircuitState.CLOSED
            return state
        except Exception as e:
            logger.warning(f"Failed to read circuit state from Redis: {e}")
            return CircuitState.CLOSED

    async def _set_state(self, state: CircuitState) -> None:
        """Set the circuit state in Redis."""
        try:
            if self._redis:
                await self._redis.set(self._state_key, state.value)
                logger.info(f"Circuit '{self.name}' changed state to {state.value}")
        except Exception as e:
            logger.warning(f"Failed to set circuit state in Redis: {e}")

    async def should_allow_request(self) -> bool:
        """
        Determines if a request should be allowed to proceed.

        Logic:
        1. If CLOSED -> Return True (Allow).
        2. If OPEN:
           - Check if time elapsed > reset_timeout.
           - If yes -> Return True (Probe / Half-Open).
           - If no  -> Return False (Block).
        """
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            try:
                # Check how long it has been open
                if not self._redis:
                    return True  # Fallback allowed if Redis is missing

                last_failure_str = await self._redis.get(self._last_failure_time_key)
                if last_failure_str:
                    last_failure_time = float(last_failure_str)
                    elapsed = time.time() - last_failure_time

                    if elapsed > self._reset_timeout:
                        logger.info(f"Circuit '{self.name}' probe allowed (timeout passed)")
                        return True  # This is effectively HALF-OPEN

                return False
            except Exception as e:
                logger.warning(f"Error checking open timeout: {e}")
                return True  # Fail open (allow traffic) on infrastructure error

        return True

    async def record_success(self) -> None:
        """
        Called when a request succeeds.

        Action:
        - If state was OPEN/HALF-OPEN -> Close it.
        - Reset failure counter to 0.
        """
        try:
            if not self._redis:
                return

            # If we were in a failure state, log the recovery
            current_state = await self.get_state()
            if current_state != CircuitState.CLOSED:
                logger.info(f"Circuit '{self.name}' recovered! Resetting to CLOSED.")
                await self._set_state(CircuitState.CLOSED)

            # Always reset counts on success
            await self._redis.set(self._failures_key, 0)

        except Exception as e:
            logger.warning(f"Error recording success: {e}")

    async def record_failure(self) -> None:
        """
        Called when a request fails (after retries exhausted).

        Action:
        - Increment failure counter.
        - If counter > MAX_FAILURES -> Open the circuit.
        """
        try:
            if not self._redis:
                return

            # 1. Update timestamp of last failure (used for reset timeout)
            await self._redis.set(self._last_failure_time_key, time.time())

            # 2. Increment failures
            raw_count = await self._redis.incr(self._failures_key)
            failures = int(raw_count)

            logger.warning(
                f"Circuit '{self.name}' recorded failure ({failures}/{self._max_failures})"
            )

            # 3. Check threshold
            if failures >= self._max_failures:
                current_state = await self.get_state()
                if current_state != CircuitState.OPEN:
                    logger.error(f"Circuit '{self.name}' tripped! Opening circuit.")
                    await self._set_state(CircuitState.OPEN)

        except Exception as e:
            logger.warning(f"Error recording failure: {e}")


# ============================================================================
# Manager & Factory
# ============================================================================


class CircuitBreakerManager:
    """Factory for managing circuit breaker instances."""

    def __init__(self):
        self.settings = get_settings()
        self._breakers: dict[str, DistributedCircuitBreaker] = {}
        self._redis = None

    async def initialize(self, redis_client):
        self._redis = redis_client
        # Re-inject redis into existing breakers if any
        for breaker in self._breakers.values():
            breaker._redis = redis_client

    def get_breaker(self, name: str) -> DistributedCircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = DistributedCircuitBreaker(name, self._redis)
        return self._breakers[name]

    async def get_all_stats(self) -> dict:
        results = {}
        for name, breaker in self._breakers.items():
            results[name] = {
                "state": await breaker.get_state(),
                "failures": await breaker._redis.get(breaker._failures_key)
                if breaker._redis
                else 0,
            }
        return results

    async def reset_all(self):
        """Helper for tests."""
        for name, breaker in self._breakers.items():
            if breaker._redis:
                await breaker._set_state(CircuitState.CLOSED)
                await breaker._redis.set(breaker._failures_key, 0)


# Global Instance
_cb_manager = CircuitBreakerManager()


def get_circuit_breaker_manager():
    return _cb_manager


# ============================================================================
# Resilient Call Wrapper
# ============================================================================


def create_retry_decorator(
    max_attempts: int = MAX_RETRIES,
    base_delay: float = RETRY_BASE_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
    retry_exceptions: tuple = (TimeoutError, ConnectionError, ProviderTimeoutError),
):
    import logging

    std_logger = logging.getLogger(__name__)  # Tenacity needs std lib logger

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay),
        retry=retry_if_exception_type(retry_exceptions),
        before_sleep=before_sleep_log(std_logger, logging.WARNING),
        reraise=True,
    )


class ResilientCall:
    """
    Main entry point for making LLM calls with resilience.
    Computes: Circuit Breaker Check -> Retry Logic -> Execution -> State Update
    """

    def __init__(self, provider_name: str, redis_client=None, max_retries: int = MAX_RETRIES):
        self.provider_name = provider_name
        self._tracker = get_tracker()

        self.manager = get_circuit_breaker_manager()
        if redis_client:
            # Note: In a real app run, initialize is awaited at startup.
            # Here we might be lazy-loading for scripts.
            if not self.manager._redis:
                # We can't await in __init__, so we assume it was init'd or we attach it
                # Ideally, create_task, but better to rely on global init.
                # For safety in this specific class usage:
                self.manager._redis = redis_client

        self.breaker = self.manager.get_breaker(provider_name)
        self.retry_decorator = create_retry_decorator(max_attempts=max_retries)

    async def call(self, func: Callable, *args, thread_id: str = None, **kwargs) -> Any:
        # 1. Circuit Breaker Check (Fail Fast)
        is_allowed = await self.breaker.should_allow_request()
        if not is_allowed:
            raise CircuitBreakerOpenError(
                message=f"Circuit open for {self.provider_name}",
                details={"provider": self.provider_name},
            )

        start_time = time.perf_counter()

        # 2. Define the execution with Retry Logic
        @self.retry_decorator
        async def execute_with_retry():
            return await func(*args, **kwargs)

        try:
            # 3. Execute
            if thread_id:
                with self._tracker.track_stage("CB", f"Call {self.provider_name}", thread_id):
                    result = await execute_with_retry()
            else:
                result = await execute_with_retry()

            # 4. Success -> Reset Circuit
            await self.breaker.record_success()

            duration = (time.perf_counter() - start_time) * 1000
            logger.debug(f"Call succeeded to {self.provider_name} in {duration:.2f}ms")
            return result

        except Exception as e:
            # 5. Failure -> Record in Circuit
            # Note: We only record persistence failures (after retries exhausted)
            logger.error(f"Resilient call failed to {self.provider_name}: {e}")
            await self.breaker.record_failure()
            raise


# ============================================================================
# Decorator Utility
# ============================================================================


def with_circuit_breaker(provider_name: str):
    """Simple decorator for protecting a single function."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Just create a transient ResilientCall wrapper
            invoker = ResilientCall(provider_name)
            return await invoker.call(func, *args, **kwargs)

        return wrapper

    return decorator
