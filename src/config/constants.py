#!/usr/bin/env python3
"""
System Constants and Enumerations

This module defines system-wide constants and enumerations used across
the SSE streaming microservice.

Architectural Decision: Centralized constants for maintainability
- Single source of truth for magic numbers
- Type-safe enums for state management
- Easy to update and track changes

Author: System Architect
Date: 2025-12-05
"""

from enum import Enum

# ============================================================================
# Stage Identifiers (for execution tracking and logging)
# ============================================================================

class Stage(str, Enum):
    """
    Request processing stages for execution tracking.

    Each stage represents a major phase in request processing.
    Used for structured logging and performance monitoring.
    """
    INITIALIZATION = "0"
    REQUEST_VALIDATION = "1"
    CACHE_LOOKUP = "2"
    RATE_LIMITING = "3"
    PROVIDER_SELECTION = "4"
    LLM_STREAMING = "5"
    CLEANUP = "6"
    CIRCUIT_BREAKER = "CB"
    RETRY = "R"
    QUEUE = "Q"
    METRICS = "M"
    LOGGING = "L"


# ============================================================================
# Circuit Breaker States
# ============================================================================

class CircuitState(str, Enum):
    """
    Circuit breaker states.

    CLOSED: Normal operation, requests allowed
    OPEN: Failing fast, requests blocked
    HALF_OPEN: Testing recovery, limited requests
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ============================================================================
# Cache Tiers
# ============================================================================

class CacheTier(str, Enum):
    """
    Multi-tier caching levels.

    L1: In-memory LRU cache (fastest, < 1ms)
    L2: Redis distributed cache (fast, 1-5ms)
    """
    L1 = "l1"
    L2 = "l2"


# ============================================================================
# LLM Providers
# ============================================================================

class LLMProvider(str, Enum):
    """
    Supported LLM providers.
    """
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"


# ============================================================================
# Request Status
# ============================================================================

class RequestStatus(str, Enum):
    """
    Request processing status.
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"


# ============================================================================
# Trace Categories (from existing codebase)
# ============================================================================

class TraceCategory(str, Enum):
    """
    Enumeration for different categories of trace events.
    """
    SYSTEM = "system"
    LLM_CLIENT = "llm_client"
    STREAMING = "streaming"
    DATABASE = "database"
    API = "api"
    CONNECTION = "connection"
    ERROR = "error"
    CACHE = "cache"
    QUEUE = "queue"


class TraceStatus(str, Enum):
    """
    Enumeration for the status of a trace event.
    """
    INFO = "info"
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    PENDING = "pending"
    ABORTED = "aborted"
    FALLBACK = "fallback"


# ============================================================================
# Performance Thresholds
# ============================================================================

# Latency thresholds (milliseconds)
LATENCY_THRESHOLD_FAST = 100  # < 100ms is fast
LATENCY_THRESHOLD_ACCEPTABLE = 1000  # < 1s is acceptable
LATENCY_THRESHOLD_SLOW = 2000  # > 2s is slow

# Connection limits
MAX_CONCURRENT_CONNECTIONS = 10000  # Maximum concurrent SSE connections
MAX_CONNECTIONS_PER_USER = 3  # Maximum connections per user

# Timeout values (seconds)
FIRST_CHUNK_TIMEOUT = 10  # First chunk must arrive within 10s
TOTAL_REQUEST_TIMEOUT = 300  # Total request timeout (5 minutes)
IDLE_CONNECTION_TIMEOUT = 1800  # Idle connection timeout (30 minutes)

# Cache sizes
L1_CACHE_MAX_SIZE = 1000  # Maximum entries in L1 cache
L2_CACHE_DEFAULT_TTL = 3600  # Default TTL for L2 cache (1 hour)

# Queue settings
QUEUE_MAX_DEPTH = 10000  # Maximum queue depth before backpressure
QUEUE_BATCH_SIZE = 50  # Batch size for queue processing

# Retry settings
MAX_RETRIES = 3  # Maximum retry attempts
RETRY_BASE_DELAY = 1.0  # Base delay for exponential backoff (seconds)
RETRY_MAX_DELAY = 30.0  # Maximum delay for exponential backoff (seconds)

# ============================================================================
# Redis Key Prefixes
# ============================================================================

REDIS_KEY_CACHE_RESPONSE = "cache:response"
REDIS_KEY_CACHE_SESSION = "cache:session"
REDIS_KEY_CIRCUIT = "circuit"
REDIS_KEY_RATE_LIMIT = "ratelimit"
REDIS_KEY_METRICS = "metrics"
REDIS_KEY_THREAD_META = "meta:thread"

# ============================================================================
# HTTP Headers
# ============================================================================

HEADER_THREAD_ID = "X-Thread-ID"
HEADER_REQUEST_ID = "X-Request-ID"
HEADER_RATE_LIMIT = "X-RateLimit-Limit"
HEADER_RATE_REMAINING = "X-RateLimit-Remaining"
HEADER_RATE_RESET = "X-RateLimit-Reset"

# ============================================================================
# SSE Event Types
# ============================================================================

SSE_EVENT_CHUNK = "chunk"
SSE_EVENT_STATUS = "status"
SSE_EVENT_ERROR = "error"
SSE_EVENT_COMPLETE = "complete"
SSE_EVENT_HEARTBEAT = "heartbeat"

# Heartbeat interval (seconds)
SSE_HEARTBEAT_INTERVAL = 30
