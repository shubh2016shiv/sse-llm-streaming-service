# Testing Strategy & Coverage Matrix

## Overview
Comprehensive unit testing strategy for the SSE streaming microservice using pytest/uv with focus on:
- Pure unit tests with mocked dependencies
- Integration-style tests with real services behind env flags
- Edge case coverage driven by main code analysis

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
- Isolated component testing with mocked dependencies
- Fast execution, deterministic results
- AAA pattern: Arrange-Act-Assert
- Focus: Business logic, state transitions, error handling

### Integration Tests (`@pytest.mark.integration`)
- Component interaction testing
- Optional live services (Redis, providers) via environment flags
- Slower execution, may be skipped in CI

## IO Policy

### Pure Unit Tests (Default)
- All external I/O mocked (Redis, HTTP, file system)
- Deterministic, fast execution
- No network dependencies

### Integration-Style Tests (Optional)
- Real Redis when `USE_REAL_REDIS=1`
- Real provider APIs when `USE_REAL_PROVIDERS=1`
- Controlled via environment variables
- Can be skipped in CI for stability

## Coverage Targets by Module

### Core Layer (90%+ Target)

| Module | Coverage Target | Priority | Current Status | Test File |
|--------|----------------|----------|----------------|-----------|
| `resilience/circuit_breaker.py` | 95% | Critical | Partial | `test_circuit_breaker.py` |
| `resilience/rate_limiter.py` | 90% | High | None | TBD |
| `observability/execution_tracker.py` | 95% | Critical | Partial | `test_execution_tracker.py` |
| `config/settings.py` | 80% | Medium | None | TBD |
| `config/constants.py` | 90% | High | None | TBD |
| `exceptions/base.py` | 85% | Medium | None | TBD |
| `logging/logger.py` | 75% | Low | None | TBD |

### Infrastructure Layer (85%+ Target)

| Module | Coverage Target | Priority | Current Status | Test File |
|--------|----------------|----------|----------------|-----------|
| `cache/cache_manager.py` | 90% | Critical | Partial | `test_cache_manager.py` |
| `cache/redis_client.py` | 85% | High | None | TBD |
| `message_queue/factory.py` | 90% | High | None | TBD |
| `message_queue/kafka_queue.py` | 80% | Medium | None | TBD |
| `message_queue/redis_queue.py` | 80% | Medium | None | TBD |
| `monitoring/health_checker.py` | 85% | Medium | None | TBD |
| `monitoring/metrics_collector.py` | 85% | Medium | None | TBD |

### LLM Stream Layer (85%+ Target)

| Module | Coverage Target | Priority | Current Status | Test File |
|--------|----------------|----------|----------------|-----------|
| `services/stream_orchestrator.py` | 95% | Critical | Partial | `test_stream_orchestrator.py` |
| `providers/base_provider.py` | 90% | High | None | TBD |
| `providers/openai_provider.py` | 85% | High | None | TBD |
| `providers/gemini_provider.py` | 85% | High | None | TBD |
| `providers/deepseek_provider.py` | 85% | High | None | TBD |
| `providers/fake_provider.py` | 90% | High | None | TBD |
| `models/stream_request.py` | 90% | High | None | TBD |

### Application Layer (80%+ Target)

| Module | Coverage Target | Priority | Current Status | Test File |
|--------|----------------|----------|----------------|-----------|
| `validators/stream_validator.py` | 90% | High | None | TBD |
| `api/routes/health.py` | 85% | Medium | None | TBD |
| `api/routes/streaming.py` | 90% | High | None | TBD |
| `api/routes/admin.py` | 80% | Low | None | TBD |
| `api/dependencies.py` | 85% | Medium | None | TBD |
| `app.py` | 75% | Low | None | TBD |

## Test Structure

```
tests/
├── unit/
│   ├── core_layer/
│   ├── infrastructure_layer/
│   ├── llm_stream_layer/
│   └── application_layer/
├── integration/
├── conftest.py
├── test_fixtures/
└── TESTING_STRATEGY.md (this file)
```

## Execution Commands

```bash
# Run all unit tests
uv run pytest -m unit

# Run specific layer
uv run pytest tests/unit/core_layer/

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run integration tests (if enabled)
USE_REAL_REDIS=1 uv run pytest -m integration

# Quick smoke test
uv run pytest -m smoke --tb=short
```

## Key Testing Patterns

1. **Dependency Injection**: Mock all external dependencies
2. **Async Testing**: Use `pytest-asyncio` for async functions
3. **Statistical Validation**: Test probabilistic algorithms with ranges
4. **Error Path Coverage**: Test all exception branches
5. **State Machine Testing**: Cover all state transitions
6. **Fixture Reuse**: Shared mocks in `conftest.py`




