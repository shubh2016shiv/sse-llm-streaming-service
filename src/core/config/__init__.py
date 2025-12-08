"""
Configuration Module

This module provides centralized, type-safe configuration management
for the SSE streaming microservice.

Components:
-----------
- **settings.py**: Pydantic-based configuration with environment variable loading
- **constants.py**: System-wide constants, enums, and magic numbers
- **provider_registry.py**: LLM provider registration logic

Architecture:
------------
The configuration module follows a layered approach:

1. **Constants Layer** (`constants.py`):
   - Immutable system constants
   - Type-safe enums (Stage, CircuitState, CacheTier, etc.)
   - Performance thresholds
   - Redis key prefixes
   - HTTP headers

2. **Settings Layer** (`settings.py`):
   - Environment-based configuration
   - Pydantic validation
   - Nested settings objects (redis, llm, circuit_breaker, etc.)
   - Singleton pattern for global access

3. **Provider Registry** (`provider_registry.py`):
   - LLM provider registration
   - Conditional registration based on API keys
   - Factory pattern integration

Usage:
------
```python
from src.core.config import get_settings
from src.core.config.constants import Stage, CircuitState
from src.core.config.provider_registry import register_providers

# Get settings
settings = get_settings()

# Access nested settings
redis_host = settings.redis.REDIS_HOST
openai_key = settings.llm.OPENAI_API_KEY

# Use constants
stage = Stage.CACHE_LOOKUP  # "2.0_CACHE_LOOKUP"
state = CircuitState.CLOSED  # "closed"

# Register providers
register_providers()
```

Type Safety:
-----------
All configuration uses modern Python typing:
- `str | None` for optional strings
- `Literal["json", "console"]` for enums
- `list[str]` for lists
- `dict[str, Any]` for dictionaries
- Pydantic `Field` for validation

Environment Variables:
---------------------
Configuration is loaded from environment variables or `.env` file:

```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_MAX_CONNECTIONS=200

# LLM Providers
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
GOOGLE_API_KEY=...

# Circuit Breaker
CB_FAILURE_THRESHOLD=5
CB_RECOVERY_TIMEOUT=60

# Rate Limiting
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_PREMIUM=1000/minute

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Application
ENVIRONMENT=production
DEBUG=false
```

Validation:
----------
Settings are validated at startup using Pydantic:
- Type checking
- Range validation
- Custom validators
- Fail-fast on misconfiguration

Example:
```python
# Invalid log level raises ValueError
LOG_LEVEL=INVALID  # ❌ Raises: LOG_LEVEL must be one of ['DEBUG', 'INFO', ...]

# Invalid type raises ValidationError
REDIS_PORT=abc  # ❌ Raises: Input should be a valid integer
```

Best Practices:
--------------
1. **Use get_settings() for access**: Don't instantiate Settings directly
2. **Access via nested objects**: `settings.redis.REDIS_HOST` not `settings.REDIS_HOST`
3. **Use constants for magic numbers**: `Stage.CACHE_LOOKUP` not `"2.0_CACHE_LOOKUP"`
4. **Validate early**: Settings are validated at import time
5. **Test with overrides**: Use `reload_settings()` for testing

Testing:
-------
```python
import os
from src.core.config import reload_settings

# Override settings for testing
os.environ["REDIS_HOST"] = "test-redis"
os.environ["LOG_LEVEL"] = "DEBUG"

settings = reload_settings()
assert settings.redis.REDIS_HOST == "test-redis"
```

Author: System Architect
Date: 2025-12-05
"""

from src.core.config.constants import (
    FIRST_CHUNK_TIMEOUT,
    HEADER_RATE_LIMIT,
    HEADER_RATE_REMAINING,
    HEADER_RATE_RESET,
    HEADER_REQUEST_ID,
    HEADER_THREAD_ID,
    IDLE_CONNECTION_TIMEOUT,
    L1_CACHE_MAX_SIZE,
    L2_CACHE_DEFAULT_TTL,
    LATENCY_THRESHOLD_ACCEPTABLE,
    LATENCY_THRESHOLD_FAST,
    LATENCY_THRESHOLD_SLOW,
    MAX_CONCURRENT_CONNECTIONS,
    MAX_CONNECTIONS_PER_USER,
    MAX_RETRIES,
    QUEUE_BACKPRESSURE_MAX_RETRIES,
    QUEUE_BACKPRESSURE_THRESHOLD,
    QUEUE_BATCH_SIZE,
    QUEUE_MAX_DEPTH,
    REDIS_KEY_CACHE_RESPONSE,
    REDIS_KEY_CACHE_SESSION,
    REDIS_KEY_CIRCUIT,
    REDIS_KEY_METRICS,
    REDIS_KEY_RATE_LIMIT,
    REDIS_KEY_THREAD_META,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    SSE_EVENT_CHUNK,
    SSE_EVENT_COMPLETE,
    SSE_EVENT_ERROR,
    SSE_EVENT_HEARTBEAT,
    SSE_EVENT_STATUS,
    SSE_HEARTBEAT_INTERVAL,
    TOTAL_REQUEST_TIMEOUT,
    CacheTier,
    CircuitState,
    LLMProvider,
    RequestStatus,
    Stage,
    TraceCategory,
    TraceStatus,
)
from src.core.config.settings import get_settings, reload_settings

# NOTE: provider_registry is not imported here to avoid circular imports
# Import it directly when needed: from src.core.config.provider_registry import register_providers

__all__ = [
    # Settings
    "get_settings",
    "reload_settings",
    # Enums
    "Stage",
    "CircuitState",
    "CacheTier",
    "LLMProvider",
    "RequestStatus",
    "TraceCategory",
    "TraceStatus",
    # Performance thresholds
    "LATENCY_THRESHOLD_FAST",
    "LATENCY_THRESHOLD_ACCEPTABLE",
    "LATENCY_THRESHOLD_SLOW",
    # Connection limits
    "MAX_CONCURRENT_CONNECTIONS",
    "MAX_CONNECTIONS_PER_USER",
    # Timeouts
    "FIRST_CHUNK_TIMEOUT",
    "TOTAL_REQUEST_TIMEOUT",
    "IDLE_CONNECTION_TIMEOUT",
    # Cache
    "L1_CACHE_MAX_SIZE",
    "L2_CACHE_DEFAULT_TTL",
    # Queue
    "QUEUE_MAX_DEPTH",
    "QUEUE_BATCH_SIZE",
    "QUEUE_BACKPRESSURE_THRESHOLD",
    "QUEUE_BACKPRESSURE_MAX_RETRIES",
    # Retry
    "MAX_RETRIES",
    "RETRY_BASE_DELAY",
    "RETRY_MAX_DELAY",
    # Redis keys
    "REDIS_KEY_CACHE_RESPONSE",
    "REDIS_KEY_CACHE_SESSION",
    "REDIS_KEY_CIRCUIT",
    "REDIS_KEY_RATE_LIMIT",
    "REDIS_KEY_METRICS",
    "REDIS_KEY_THREAD_META",
    # HTTP headers
    "HEADER_THREAD_ID",
    "HEADER_REQUEST_ID",
    "HEADER_RATE_LIMIT",
    "HEADER_RATE_REMAINING",
    "HEADER_RATE_RESET",
    # SSE events
    "SSE_EVENT_CHUNK",
    "SSE_EVENT_STATUS",
    "SSE_EVENT_ERROR",
    "SSE_EVENT_COMPLETE",
    "SSE_EVENT_HEARTBEAT",
    "SSE_HEARTBEAT_INTERVAL",
]
