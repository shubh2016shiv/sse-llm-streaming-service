# Testing Infrastructure

> **Professional testing setup demonstrating production-grade software engineering practices.**

## 📁 Directory Structure

```
tests/
├── unit/                          # Fast, isolated unit tests
│   ├── core_layer/                # Core domain logic tests
│   │   └── test_execution_tracker.py
│   └── service_layer/             # Service orchestration tests
│       └── test_stream_orchestrator.py
│
├── integration/                   # Component integration tests
│   └── (future: Redis, cache, providers)
│
├── test_fixtures/                 # Shared test data
│   └── (future: sample requests, responses)
│
├── conftest.py                    # Pytest configuration & fixtures
└── README.md                      # This file
```

## 🎯 Testing Philosophy

This test suite demonstrates **professional engineering practices**:

- ✅ **Dependency Injection**: Easy to mock, fast to run
- ✅ **Clear Test Names**: `test_cache_hit_returns_cached_response_immediately`
- ✅ **AAA Pattern**: Arrange → Act → Assert
- ✅ **Comprehensive Fixtures**: Reusable mocks in `conftest.py`
- ✅ **Statistical Validation**: Sampling algorithm correctness
- ✅ **Edge Case Coverage**: 0%, 100% sample rates

## 🚀 Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run specific test file
uv run pytest tests/unit/service_layer/test_stream_orchestrator.py

# Run only unit tests
uv run pytest -m unit

# Run with verbose output
uv run pytest -v
```

## 📊 Coverage Goals

| Component | Target | Priority | Status |
|-----------|--------|----------|--------|
| StreamOrchestrator | 100% | Critical | ✅ |
| ExecutionTracker | 100% | Critical | ✅ |
| CircuitBreaker | 95% | High | 🔄 |
| CacheManager | 90% | High | 🔄 |
| Providers | 80% | Medium | 🔄 |

## 💡 Key Testing Patterns

### 1. Dependency Injection Makes Testing Easy

```python
# No mocking globals - just inject mocks!
orchestrator = StreamOrchestrator(
    cache_manager=mock_cache,      # Injected
    provider_factory=mock_factory,  # Injected
    execution_tracker=mock_tracker  # Injected
)
```

### 2. Shared Fixtures in conftest.py

```python
@pytest.fixture
def mock_cache_manager():
    """Reusable across ALL tests."""
    cache = AsyncMock(spec=CacheManager)
    cache.get = AsyncMock(return_value=None)
    return cache
```

### 3. Statistical Validation

```python
def test_sampling_distribution(tracker):
    """Verify 10% sample rate is statistically correct."""
    tracked = sum(1 for i in range(10000) 
                  if tracker.should_track(f"thread-{i}"))
    
    actual_rate = tracked / 10000
    assert 0.08 <= actual_rate <= 0.12  # Within 2%
```

## 🧪 Test Examples

### Unit Test: Cache Hit Path
```python
@pytest.mark.asyncio
async def test_cache_hit_returns_cached_response_immediately(
    orchestrator, sample_stream_request, mock_cache_manager
):
    # Arrange
    mock_cache_manager.get = AsyncMock(return_value="Cached!")

    # Act
    events = [e async for e in orchestrator.stream(sample_stream_request)]

    # Assert
    assert events[1].data["cached"] is True
```

## 🎓 For Recruiters

This testing infrastructure showcases:

- **Test-Driven Development**: Tests written alongside production code
- **Mocking & Isolation**: Proper use of test doubles
- **Async Testing**: Handling `async/await` in tests
- **Statistical Rigor**: Validating probabilistic algorithms
- **Clean Code**: Readable, maintainable test code
- **Professional Tooling**: pytest, pytest-asyncio, pytest-cov

## 📈 Next Steps

- [ ] Add integration tests with test containers (Redis)
- [ ] Add E2E tests for complete request workflows
- [ ] Set up CI/CD with GitHub Actions
- [ ] Add performance benchmarks
- [ ] Achieve 90%+ overall coverage

## 🔧 Configuration

Test configuration is in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "unit: marks tests as unit tests",
    "integration: marks tests as integration tests",
]
```

All test dependencies are managed via UV in `pyproject.toml` - no separate requirements file needed.
