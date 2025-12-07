# ADR-003: Hash-Based Execution Tracking Sampling

**Status**: Accepted  
**Date**: 2025-12-05  
**Decision Makers**: System Architect  
**Tags**: #observability #performance #sampling

## Context

Execution tracking provides valuable performance insights:
- Stage-by-stage timing (identify bottlenecks)
- Success/failure tracking (debug issues)
- Percentile calculations (p50, p95, p99)

However, tracking **every** request has significant memory overhead:
- **Without sampling**: 10,000 requests/min × 10 stages × 200 bytes = ~20 MB/min
- **Over 1 hour**: ~1.2 GB of memory
- **Over 24 hours**: ~28.8 GB of memory (unsustainable)

We need to reduce memory usage while maintaining observability.

## Decision

Implement **hash-based sampling** to track only a percentage of requests (default: 10%):

### Algorithm: Consistent Hash-Based Sampling

```python
def should_track(thread_id: str, sample_rate: float) -> bool:
    # Hash thread_id to integer
    hash_value = int(hashlib.md5(thread_id.encode()).hexdigest(), 16)
    
    # Map to percentage bucket (0-99)
    bucket = hash_value % 100
    
    # Compare against threshold
    return bucket < (sample_rate * 100)
```

### Key Properties
1. **Deterministic**: Same `thread_id` always gets same decision
2. **Consistent**: If we track stage 1, we track ALL stages for that request
3. **Uniform**: Even distribution across all requests
4. **Fast**: ~2 microseconds per call

## Visual Example

```
Sample Rate = 10%

thread_id "req-001" → MD5 → hash % 100 = 5  → 5 < 10  → TRACK ✓
thread_id "req-002" → MD5 → hash % 100 = 47 → 47 < 10 → DON'T TRACK ✗
thread_id "req-003" → MD5 → hash % 100 = 8  → 8 < 10  → TRACK ✓

Result: ~10% of requests tracked consistently
```

## Consequences

### ✅ Pros
1. **90% memory reduction** (10% sampling)
2. **Consistent tracking**: Complete traces for sampled requests
3. **Statistical validity**: 1,000 samples sufficient for percentiles
4. **Deterministic**: Reproducible behavior (same input → same output)
5. **Fast**: Negligible CPU overhead (~2 μs)

### ⚠️ Cons
1. **Incomplete data**: Only see 10% of requests
2. **Rare events missed**: Low-probability issues might not be sampled
3. **Not cryptographically secure**: MD5 is not secure (but we don't need security)

## Alternatives Considered

### Alternative 1: Random sampling
- **Rejected**: Inconsistent (might track stage 1 but not stage 2)
- **Analysis**: Would create incomplete traces (useless for debugging)

### Alternative 2: Track everything
- **Rejected**: Unsustainable memory usage (~28 GB/day)
- **Analysis**: Not viable at scale

### Alternative 3: Time-based sampling (track first N requests per minute)
- **Rejected**: Biased (only tracks early requests, misses peak load)
- **Analysis**: Doesn't represent true traffic patterns

## Statistical Validity

### Sample Size Analysis
- **10% of 10,000 requests** = 1,000 samples
- **Margin of error**: ±3% at 95% confidence level
- **Percentile accuracy**: Sufficient for p50, p95, p99

### When to Increase Sampling
- **Low traffic** (< 1,000 requests/hour): Use 100% sampling
- **Medium traffic** (1,000-10,000/hour): Use 10-50% sampling
- **High traffic** (> 10,000/hour): Use 1-10% sampling

## Performance Impact

### Memory Savings
```
Without sampling (100%):
- 10,000 req/min × 10 stages × 200 bytes = 20 MB/min
- Over 1 hour: 1.2 GB

With 10% sampling:
- 1,000 req/min × 10 stages × 200 bytes = 2 MB/min
- Over 1 hour: 120 MB
- **90% reduction**
```

### CPU Impact
- **Hash computation**: ~2 microseconds per request
- **Percentage of request time**: < 0.01%
- **Negligible overhead**

## Configuration

```python
# settings.py
EXECUTION_TRACKING_SAMPLE_RATE = 0.1  # 10% sampling

# Override for debugging
tracker.track_stage("stage_id", "name", thread_id, force_tracking=True)
```

## Monitoring

Track sampling effectiveness:
```python
# Prometheus metrics
execution_tracking_samples_total
execution_tracking_sample_rate
execution_tracking_memory_bytes
```

## Implementation

- **File**: `src/core/observability/execution_tracker.py`
- **Method**: `ExecutionTracker.should_track()`
- **Configuration**: `EXECUTION_TRACKING_SAMPLE_RATE`

## Related ADRs

- ADR-001: Multi-tier caching strategy
- ADR-006: Prometheus metrics design

## References

- [Sampling Strategies](https://opentelemetry.io/docs/concepts/sampling/)
- [Hash-Based Sampling](https://en.wikipedia.org/wiki/Consistent_hashing)
- [Statistical Sampling](https://en.wikipedia.org/wiki/Sampling_(statistics))
