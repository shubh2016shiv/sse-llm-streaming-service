# ADR-002: Circuit Breaker with Redis Coordination

**Status**: Accepted  
**Date**: 2025-12-05  
**Decision Makers**: System Architect  
**Tags**: #resilience #circuit-breaker #distributed-systems

## Context

In a distributed system with multiple LLM providers (OpenAI, DeepSeek, Gemini), providers can fail or become slow:
- **Network issues**: Timeouts, connection errors
- **Rate limiting**: Provider-side throttling
- **Service degradation**: Slow responses, partial outages
- **Cascading failures**: One failing provider affecting others

Without circuit breakers:
- Failed requests keep retrying (wasting time and resources)
- Slow providers block request threads (thread pool exhaustion)
- Cascading failures spread across the system
- No automatic failover to healthy providers

## Decision

Implement **distributed circuit breakers** with Redis-backed state coordination:

### Circuit Breaker States

```
┌─────────────┐
│   CLOSED    │ ◄─── Normal operation, requests flow through
│ (Healthy)   │
└──────┬──────┘
       │ Failures exceed threshold
       ▼
┌─────────────┐
│    OPEN     │ ◄─── Fail fast, reject requests immediately
│  (Failing)  │
└──────┬──────┘
       │ After timeout period
       ▼
┌─────────────┐
│ HALF_OPEN   │ ◄─── Test with limited requests
│  (Testing)  │
└──────┬──────┘
       │
       ├─ Success → CLOSED
       └─ Failure → OPEN
```

### Key Parameters
- **Failure Threshold**: 5 consecutive failures
- **Recovery Timeout**: 60 seconds
- **State Storage**: Redis (shared across all instances)
- **Excluded Exceptions**: `ValueError`, `TypeError` (validation errors don't count)

## Algorithm

### State Transition Logic

```python
# On Request
if circuit_state == OPEN:
    raise CircuitBreakerOpenError  # Fail fast
    
if circuit_state == HALF_OPEN:
    if test_request_succeeds():
        circuit_state = CLOSED
    else:
        circuit_state = OPEN
        
# On Success
reset_failure_counter()

# On Failure
increment_failure_counter()
if failure_counter >= threshold:
    circuit_state = OPEN
    start_recovery_timer()
```

### Redis Coordination

```
Circuit State Keys (per provider):
- circuit:{provider}:state → "closed" | "open" | "half_open"
- circuit:{provider}:failures → integer counter
- circuit:{provider}:opened_at → ISO timestamp
```

## Consequences

### ✅ Pros
1. **Fail fast**: Don't waste time on known-failing providers
2. **Automatic recovery**: Test providers periodically (half-open state)
3. **Distributed coordination**: All instances share circuit state via Redis
4. **Prevents cascading failures**: Isolate failing providers
5. **Automatic failover**: Select healthy providers only

### ⚠️ Cons
1. **Eventual consistency**: Redis state updates are not instant
2. **False positives**: Temporary network blips can open circuit
3. **Additional complexity**: More moving parts to monitor
4. **Redis dependency**: Circuit breaker requires Redis to be available

## Alternatives Considered

### Alternative 1: Local (per-instance) circuit breakers
- **Rejected**: Each instance makes its own decisions (inefficient)
- **Analysis**: Instance A might keep trying while Instance B knows provider is down

### Alternative 2: Database-backed circuit breaker
- **Rejected**: Too slow (database queries add latency)
- **Analysis**: Redis is faster and designed for this use case

### Alternative 3: No circuit breaker (just retries)
- **Rejected**: Wastes resources on failing providers
- **Analysis**: Retries alone don't prevent cascading failures

## Performance Impact

### Latency
- **Circuit check**: ~1ms (Redis GET operation)
- **State update**: ~2ms (Redis SET operation)
- **Fail-fast**: ~0.1ms (no network call)

### Resource Savings
- **Without circuit breaker**: 5 retries × 30s timeout = 150s wasted per request
- **With circuit breaker**: Fail fast in ~1ms
- **Savings**: ~99.9% reduction in wasted time

## Monitoring

Track these metrics:
```python
# Prometheus metrics
circuit_breaker_state{provider="openai"} → 0 (closed), 1 (open), 2 (half_open)
circuit_breaker_failures_total{provider="openai"}
circuit_breaker_trips_total{provider="openai"}
circuit_breaker_recoveries_total{provider="openai"}
```

## Implementation

- **File**: `src/core/resilience/circuit_breaker.py`
- **Classes**: `CircuitBreakerManager`, `RedisCircuitBreakerStorage`, `ResilientCall`
- **Configuration**: `CB_FAILURE_THRESHOLD`, `CB_RECOVERY_TIMEOUT`

## Related ADRs

- ADR-004: Provider failover algorithm
- ADR-005: Distributed rate limiting design

## References

- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [pybreaker Documentation](https://github.com/danielfm/pybreaker)
- [Release It! - Michael Nygard](https://pragprog.com/titles/mnee2/release-it-second-edition/)
