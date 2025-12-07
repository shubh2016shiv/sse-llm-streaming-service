# ADR-004: Provider Failover Algorithm

**Status**: Accepted  
**Date**: 2025-12-05  
**Decision Makers**: System Architect  
**Tags**: #resilience #failover #providers

## Context

The system supports multiple LLM providers (OpenAI, DeepSeek, Gemini):
- Providers can fail or become unavailable
- Users may prefer specific providers
- Need automatic failover to maintain availability
- Circuit breakers track provider health

Without intelligent failover:
- Requests fail when preferred provider is down
- No automatic recovery
- Manual intervention required
- Poor user experience

## Decision

Implement **intelligent provider failover** with circuit breaker awareness:

### Algorithm

```
1. If user specifies preferred provider:
   a. Check circuit breaker state
   b. If CLOSED (healthy), use preferred provider
   c. If OPEN (failing), proceed to step 2

2. Get all available providers
3. Filter out providers with OPEN circuit breakers
4. Sort remaining providers by health score:
   - Circuit state (CLOSED > HALF_OPEN > OPEN)
   - Recent latency (faster providers first)
   
5. Return first healthy provider
6. If NO healthy providers, raise AllProvidersDownError
```

### Visual Flow

```
User Request
    ↓
Preferred Provider?
    ├─ Yes → Check Circuit Breaker
    │         ├─ CLOSED → Use Preferred ✓
    │         └─ OPEN → Failover ↓
    │
    └─ No → Get All Providers
                ↓
         Filter by Circuit State
                ↓
         Sort by Health Score
                ↓
         Return First Healthy
                ↓
         (or raise AllProvidersDownError)
```

## Consequences

### ✅ Pros
1. **Automatic failover**: No manual intervention needed
2. **Respects user preference**: Uses preferred provider when healthy
3. **Circuit breaker aware**: Avoids known-failing providers
4. **Transparent**: User doesn't see failover (just works)
5. **High availability**: System stays up even if providers fail

### ⚠️ Cons
1. **Eventual consistency**: Circuit state updates via Redis (slight delay)
2. **Cost variation**: Different providers have different pricing
3. **Model compatibility**: Not all providers support all models
4. **Complexity**: More logic to maintain and test

## Alternatives Considered

### Alternative 1: No failover (fail on provider error)
- **Rejected**: Poor availability, bad user experience
- **Analysis**: Single provider failure = system failure

### Alternative 2: Round-robin across all providers
- **Rejected**: Doesn't respect user preference or circuit state
- **Analysis**: Would send requests to failing providers

### Alternative 3: Random provider selection
- **Rejected**: Unpredictable, doesn't optimize for health
- **Analysis**: Might select slow or failing providers

## Performance Impact

### Latency
- **Circuit state check**: ~1ms (Redis GET)
- **Provider selection**: ~0.1ms (in-memory sorting)
- **Total overhead**: ~1-2ms per request

### Availability Improvement
- **Without failover**: 99.9% (single provider SLA)
- **With failover** (3 providers): 99.9999% (six nines)
- **Calculation**: 1 - (0.001)³ = 0.999999

## Example Scenarios

### Scenario 1: Preferred provider healthy
```
User prefers: "openai"
Circuit state: CLOSED
Result: Use OpenAI ✓
```

### Scenario 2: Preferred provider failing
```
User prefers: "openai"
Circuit state: OPEN
Available: ["deepseek" (CLOSED), "gemini" (CLOSED)]
Result: Failover to DeepSeek ✓
```

### Scenario 3: All providers failing
```
Circuit states: ALL OPEN
Result: AllProvidersDownError ✗
```

## Error Handling

When all providers are down:
```python
raise AllProvidersDownError(
    "No healthy providers available",
    details={
        "circuit_states": {
            "openai": "open",
            "deepseek": "open",
            "gemini": "open"
        },
        "preferred_provider": "openai",
        "available_providers": ["openai", "deepseek", "gemini"]
    }
)
```

## Monitoring

Track failover events:
```python
# Prometheus metrics
provider_failover_total{from="openai", to="deepseek"}
provider_selection_total{provider="openai", preferred="true"}
provider_availability{provider="openai"} → 0 or 1
```

## Implementation

- **File**: `src/llm_stream/services/stream_orchestrator.py`
- **Method**: `_select_provider()`
- **Dependencies**: `CircuitBreakerManager`, `ProviderFactory`

## Related ADRs

- ADR-002: Circuit breaker with Redis coordination
- ADR-005: Distributed rate limiting design

## References

- [Failover Patterns](https://docs.microsoft.com/en-us/azure/architecture/patterns/retry)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
