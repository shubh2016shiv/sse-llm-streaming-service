"""
Resilience Module - Core Resilience Components

This module provides enterprise-grade resilience patterns for the SSE streaming
microservice, implementing the three-layer defense system:

ARCHITECTURE:
=============
Layer 1: NGINX Load Balancer (external)
    - Distributes traffic across FastAPI instances
    - least_conn algorithm for SSE connections

Layer 2: Connection Pool Manager (this module)
    - Enforces per-user (3) and global (10,000) connection limits
    - Provides backpressure via 429 errors OR queue failover

Layer 3: Message Queue Failover (this module)
    - Catches connection pool exhaustion
    - Queues requests to Redis/Kafka
    - Consumer worker processes when capacity available
    - Frontend NEVER sees 429 errors

COMPONENTS:
===========
- ConnectionPoolManager: Layer 2 - connection limiting
- QueueRequestHandler: Layer 3 - request queuing
- QueueConsumerWorker: Layer 3 - queue processing
- CircuitBreaker: Provider failure protection
- RateLimiter: Request rate control

Author: Senior Solution Architect
Date: 2025-12-09
"""

# Layer 2: Connection Pool Management
# Circuit Breaker
from .circuit_breaker import (
    CircuitBreakerManager,
    DistributedCircuitBreaker,
    get_circuit_breaker_manager,
)
from .connection_pool_manager import (
    ConnectionPoolManager,
    get_connection_pool_manager,
)
from .queue_consumer_worker import (
    QueueConsumerWorker,
    start_queue_consumer_worker,
    stop_queue_consumer_worker,
)

# Layer 3: Queue Failover
from .queue_request_handler import (
    QueuedStreamingRequest,
    QueueRequestHandler,
    get_queue_request_handler,
)

# Rate Limiting
from .rate_limiter import (
    RateLimitManager,
    get_rate_limit_manager,
)

__all__ = [
    # Layer 2
    "ConnectionPoolManager",
    "get_connection_pool_manager",
    # Layer 3
    "QueueRequestHandler",
    "QueuedStreamingRequest",
    "get_queue_request_handler",
    "QueueConsumerWorker",
    "start_queue_consumer_worker",
    "stop_queue_consumer_worker",
    # Circuit Breaker
    "DistributedCircuitBreaker",
    "CircuitBreakerManager",
    "get_circuit_breaker_manager",
    # Rate Limiting
    "get_rate_limit_manager",
    "RateLimitManager",
]
