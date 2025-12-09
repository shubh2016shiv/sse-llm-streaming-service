# ADR 007: Message Queue Failover (Third Layer of Defense)

## Status

**Accepted** - 2025-12-09

## Context

The SSE streaming microservice needs to handle millions of concurrent streaming requests without failing. While we have:

1. **Layer 1**: NGINX load balancer distributing traffic across instances
2. **Layer 2**: Connection pool manager enforcing per-user (3) and global (10,000) limits

Requests exceeding these limits receive 429 errors, negatively impacting user experience.

### Problem Statement

When the connection pool is exhausted, requests immediately fail with 429 errors. This creates:

- **Poor UX**: Users see errors during peak load
- **Wasted Capacity**: Pending requests rejected even if capacity frees up soon
- **No Smoothing**: Load spikes cause instant rejections instead of queuing

## Decision

Implement **Message Queue Failover with Distributed Pub/Sub** as the third layer of defense.

### Three-Layer Defense Architecture

```
┌─────────────────────────────────────────────────────────┐
│            LAYER 1: NGINX LOAD BALANCER                │
│     Distributes requests across FastAPI instances       │
└──────────────────────┬──────────────────────────────────┘
                       │ If all instances at capacity
                       ▼
┌─────────────────────────────────────────────────────────┐
│          LAYER 2: CONNECTION POOL MANAGER              │
│     Enforces per-user (3) and global (10,000) limits   │
└──────────────────────┬──────────────────────────────────┘
                       │ UserConnectionLimitError
                       ▼
┌─────────────────────────────────────────────────────────┐
│       LAYER 3: DISTRIBUTED QUEUE FAILOVER (NEW)        │
│                                                         │
│  1. Handler: Queues Req & Subscribes to Redis Channel   │
│  2. Worker:  Processes Req & Publishes Stream Chunks    │
│  3. Handler: Yields Chunks to User via SSE              │
│                                                         │
│  Result: TRUE STREAMING preserved even during failover! │
└─────────────────────────────────────────────────────────┘
```

### Distributed Streaming Pattern

We utilize a **Publisher-Subscriber** pattern to bridge the gap between the instance holding the client connection and the worker instance processing the AI response.

1.  **Request Handler (Instance A)**:
    - Generates `request_id`
    - Subscribes to Redis Channel: `queue:results:{request_id}`
    - Queues job to Redis Stream

2.  **Consumer Worker (Instance B)**:
    - Picks up job
    - Generates AI tokens
    - **PUBLISHES** tokens to `queue:results:{request_id}`

3.  **Request Handler (Instance A)**:
    - Receives messages from channel
    - Yields them to the open HTTP connection
    - Unsubscribes on `SIGNAL:DONE`

### Implementation Components

| Component | File | Purpose |
|-----------|------|---------|
| Queue Request Handler | `src/core/resilience/queue_request_handler.py` | Subscribes & Streams events |
| Queue Consumer Worker | `src/core/resilience/queue_consumer_worker.py` | Processes & Publishes events |
| Redis Client | `src/infrastructure/cache/redis_client.py` | Added Pub/Sub support |

### Configuration

```python
QUEUE_FAILOVER_ENABLED: bool = True
QUEUE_FAILOVER_TIMEOUT_SECONDS: int = 30
QUEUE_FAILOVER_MAX_RETRIES: int = 5
QUEUE_FAILOVER_BASE_DELAY_MS: int = 100
QUEUE_FAILOVER_MAX_DELAY_MS: int = 5000
```

## Consequences

### Positive

1. **Zero 429 Errors**: Frontend never sees capacity errors
2. **Graceful Degradation**: Load spikes handled via queuing
3. **Better UX**: Requests succeed (just take longer under load)
4. **Utilizes Existing Infrastructure**: Redis/Kafka already deployed
5. **Configurable**: All behavior controlled via settings
6. **Toggleable**: Can disable via QUEUE_FAILOVER_ENABLED=false

### Negative

1. **Increased Latency**: Queued requests wait for processing
2. **Memory Usage**: Pending Futures stored in handler
3. **Complexity**: Additional consumer worker to manage
4. **Potential Timeouts**: Requests can still timeout after 30s

### Neutral

1. **P99 Latency Increases**: Expected trade-off for 100% success rate
2. **Queue Depth Monitoring**: Need to track queue length metrics

## Alternatives Considered

### Alternative 1: Client-Side Retries
- Frontend implements retry with exponential backoff
- **Rejected**: Violates separation of concerns, complex frontend logic

### Alternative 2: Increase Connection Limits
- Simply raise per-user and global limits
- **Rejected**: Doesn't solve root cause, just delays failure

### Alternative 3: In-Memory Queue
- Queue requests in FastAPI memory without Redis/Kafka
- **Rejected**: Not distributed, lost on server restart

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| 429 Errors to Frontend | High under load | 0% |
| P50 Latency | ~50ms | ~50ms (unchanged) |
| P99 Latency | ~100ms | ~3000ms (queued) |
| Success Rate | 30% at 10 reqs | 95%+ |
| Queue Timeout Rate | N/A | <5% |

## References

- Connection Pool ADR: `docs/architecture-decisions/006-connection-pool-backpressure.md`
- Redis Queue: `src/infrastructure/message_queue/redis_queue.py`
- Kafka Queue: `src/infrastructure/message_queue/kafka_queue.py`
