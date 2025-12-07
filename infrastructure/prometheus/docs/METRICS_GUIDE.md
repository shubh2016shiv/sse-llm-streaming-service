# Prometheus Metrics Guide - SSE Streaming Application

## Table of Contents
1. [Metric Types](#metric-types)
2. [Application Metrics](#application-metrics)
3. [Design Decisions](#design-decisions)
4. [Query Patterns](#query-patterns)
5. [Best Practices](#best-practices)

---

## Metric Types

### Counter
**What**: Monotonically increasing value (only goes up)
**When to Use**: Counting events (requests, errors, cache hits)
**Example**: `sse_requests_total`

**Key Design Decision**: Why Counter for Requests?
- **Rationale**: Requests can only increase, never decrease
- **Mechanism**: Application calls `counter.inc()` on each request
- **Benefit**: `rate()` function automatically handles restarts
- **Implementation**: 
  ```python
  requests_total = Counter('sse_requests_total', 
                          'Total requests',
                          ['status', 'provider', 'model'])
  requests_total.labels(status='success', provider='openai', model='gpt-4').inc()
  ```

---

### Gauge
**What**: Value that can go up or down
**When to Use**: Current state (active connections, memory usage)
**Example**: `sse_active_connections`

**Key Design Decision**: Why Gauge for Connections?
- **Rationale**: Connections open (inc) and close (dec)
- **Mechanism**: 
  ```python
  active_connections = Gauge('sse_active_connections', 'Active SSE connections')
  # On connection open
  active_connections.inc()
  # On connection close
  active_connections.dec()
  ```
- **Benefit**: Always shows current state
- **Pitfall**: If app crashes, gauge resets to 0 (not cumulative like counter)

---

### Histogram
**What**: Samples observations into configurable buckets
**When to Use**: Measuring distributions (latency, request size)
**Example**: `sse_request_duration_seconds`

**Key Design Decision**: Histogram for Latency
- **Rationale**: Need percentiles (P50, P95, P99), not just average
- **Mechanism**:
  ```python
  request_duration = Histogram('sse_request_duration_seconds',
                               'Request duration',
                               buckets=[0.1, 0.5, 1, 2, 5, 10])
  # Record observation
  with request_duration.time():
      process_request()
  ```
- **Bucket Selection Strategy**:
  - 0.1s: Cache hits (very fast)
  - 0.5s: L2 cache hits
  - 1s: Fast LLM responses
  - 2s: Normal LLM responses
  - 5s: Slow LLM responses
  - 10s: Very slow (approaching timeout)
  - +Inf: Everything else

**Why These Buckets?**:
- Cover expected latency range
- Granular where it matters (0.1-2s)
- Coarser for outliers (5-10s)
- Balance: Accuracy vs memory usage

**Histogram Internals**:
```
Bucket     Count    Cumulative
le="0.1"   100      100        (100 requests < 0.1s)
le="0.5"   50       150        (50 requests between 0.1-0.5s)
le="1.0"   30       180        (30 requests between 0.5-1.0s)
le="2.0"   15       195        (15 requests between 1.0-2.0s)
le="5.0"   4        199        (4 requests between 2.0-5.0s)
le="10.0"  1        200        (1 request between 5.0-10.0s)
le="+Inf"  0        200        (0 requests > 10.0s)
```

**Calculating P95**:
- Total samples: 200
- P95 position: 200 × 0.95 = 190
- 190th sample falls in le="2.0" bucket
- `histogram_quantile(0.95, ...)` interpolates: ~1.8s

---

### Summary
**What**: Similar to histogram, but calculates quantiles on client side
**When to Use**: Rarely (histograms are better)
**Why Not Use**: Cannot aggregate across instances

**Key Design Decision**: Histogram over Summary
- **Rationale**: Need to aggregate P95 across all instances
- **Mechanism**: 
  - Histogram: Buckets can be summed, then calculate quantile
  - Summary: Quantiles calculated per-instance, cannot sum
- **Example**:
  ```promql
  # Histogram: Works! ✅
  histogram_quantile(0.95, 
    sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
  )
  
  # Summary: Doesn't work! ❌
  # Cannot sum pre-calculated quantiles
  ```

---

## Application Metrics

### Request Metrics

#### `sse_requests_total`
**Type**: Counter
**Labels**: `status`, `provider`, `model`, `priority`
**Description**: Total number of requests processed

**Design Decision**: Rich Label Set
- **Rationale**: Enable multi-dimensional analysis
- **Mechanism**: Labels added at request completion
  ```python
  metrics.record_request(
      status='success',
      provider='openai',
      model='gpt-4',
      priority='HIGH'
  )
  ```
- **Query Examples**:
  ```promql
  # Total requests
  sum(sse_requests_total)
  
  # Requests by provider
  sum(sse_requests_total) by (provider)
  
  # OpenAI error rate
  rate(sse_requests_total{provider="openai", status!="success"}[5m])
  ```

**Label Cardinality Consideration**:
- **Problem**: Too many unique label combinations = memory explosion
- **Safe**: `status` (5 values) × `provider` (3 values) × `model` (10 values) × `priority` (3 values) = 450 combinations
- **Unsafe**: Adding `user_id` label (10,000 users) = 4.5M combinations!
- **Rule**: Never use high-cardinality values (user IDs, request IDs) as labels

---

#### `sse_request_duration_seconds`
**Type**: Histogram
**Labels**: `provider`, `model`
**Buckets**: `[0.1, 0.5, 1, 2, 5, 10]`
**Description**: Request latency distribution

**Design Decision**: Exclude Status Label
- **Rationale**: Failed requests have different latency profile
- **Mechanism**: Only record duration for successful requests
- **Benefit**: P95 latency reflects actual user experience, not error timeouts

---

### Stage Metrics

#### `sse_stage_duration_seconds`
**Type**: Histogram
**Labels**: `stage`
**Buckets**: `[0.001, 0.01, 0.1, 0.5, 1, 2]`
**Description**: Duration of each processing stage

**Design Decision**: Per-Stage Tracking
- **Rationale**: Identify bottlenecks in request pipeline
- **Mechanism**: Execution tracker records each stage
  ```python
  stages = [
      'validation',      # ~1ms
      'cache_lookup',    # ~5ms (L2) or ~1ms (L1)
      'rate_limit',      # ~2ms
      'provider_select', # ~1ms
      'llm_stream',      # ~1-3s
      'cleanup'          # ~1ms
  ]
  ```
- **Benefit**: Pinpoint slow stage
  ```promql
  # Which stage is slowest?
  histogram_quantile(0.95,
    sum(rate(sse_stage_duration_seconds_bucket[5m])) by (stage, le)
  )
  ```

**Expected Stage Latencies**:
| Stage | P50 | P95 | Notes |
|-------|-----|-----|-------|
| validation | 1ms | 2ms | Pydantic validation |
| cache_lookup | 1ms | 10ms | L1 hit vs L2 hit |
| rate_limit | 1ms | 5ms | Redis check |
| provider_select | 1ms | 2ms | Circuit breaker check |
| llm_stream | 500ms | 3s | LLM generation |
| cleanup | 1ms | 2ms | Cache write |

---

### Cache Metrics

#### `sse_cache_hits_total` / `sse_cache_misses_total`
**Type**: Counter
**Labels**: `tier` (L1 or L2)
**Description**: Cache hit/miss counts

**Design Decision**: Two-Tier Cache Tracking
- **Rationale**: Different performance characteristics
- **Mechanism**:
  ```python
  # L1 (in-memory) check
  if key in l1_cache:
      cache_hits.labels(tier='L1').inc()
      return l1_cache[key]
  
  # L2 (Redis) check
  if redis.exists(key):
      cache_hits.labels(tier='L2').inc()
      value = redis.get(key)
      l1_cache[key] = value  # Populate L1
      return value
  
  # Cache miss
  cache_misses.labels(tier='L2').inc()
  value = call_llm()
  redis.set(key, value, ex=3600)  # Store in L2
  l1_cache[key] = value           # Store in L1
  return value
  ```

**Why Two Tiers?**:
- **L1 (In-Memory)**:
  - Pros: Ultra-fast (~1ms), no network
  - Cons: Per-instance (not shared), lost on restart, limited size
- **L2 (Redis)**:
  - Pros: Shared across instances, persistent, larger capacity
  - Cons: Slower (~5ms), network dependency

**Hit Rate Calculation**:
```promql
# L2 hit rate
(
  sum(rate(sse_cache_hits_total{tier="L2"}[5m]))
  /
  (
    sum(rate(sse_cache_hits_total{tier="L2"}[5m]))
    +
    sum(rate(sse_cache_misses_total{tier="L2"}[5m]))
  )
) * 100
```

**Cache Effectiveness**:
- 95% hit rate = 20x reduction in LLM calls
- Cost savings: $1000/month → $50/month
- Latency improvement: 2s → 5ms (400x faster)

---

### Circuit Breaker Metrics

#### `sse_circuit_breaker_state`
**Type**: Gauge
**Labels**: `provider`
**Values**: `0` (closed), `1` (half-open), `2` (open)
**Description**: Current circuit breaker state

**Design Decision**: Gauge for State Tracking
- **Rationale**: State can transition in any direction
- **Mechanism**:
  ```python
  class CircuitBreakerState(Enum):
      CLOSED = 0      # Normal operation
      HALF_OPEN = 1   # Testing if recovered
      OPEN = 2        # Blocking requests
  
  # Update gauge on state change
  circuit_breaker_state.labels(provider='openai').set(
      CircuitBreakerState.OPEN.value
  )
  ```

**State Transitions**:
```
CLOSED → OPEN: After 5 consecutive failures
OPEN → HALF_OPEN: After 60-second timeout
HALF_OPEN → CLOSED: After 1 successful request
HALF_OPEN → OPEN: After any failure
```

**Why Circuit Breaker?**:
- **Problem**: Provider down → all requests fail → waste time/resources
- **Solution**: Detect failure pattern → fail fast → retry periodically
- **Benefit**: Faster error response, reduced load on failing provider

**Alert on Open State**:
```promql
# Alert if circuit open for >1 minute
sse_circuit_breaker_state == 2
```

---

#### `sse_circuit_breaker_failures_total`
**Type**: Counter
**Labels**: `provider`
**Description**: Total failures recorded by circuit breaker

**Design Decision**: Track Failures Separately
- **Rationale**: Detect degradation before circuit opens
- **Mechanism**: Increment on each failure, even if circuit still closed
- **Benefit**: Early warning alert
  ```promql
  # Alert if failure rate high (approaching open threshold)
  rate(sse_circuit_breaker_failures_total[5m]) > 0.5
  ```

---

### Provider Metrics

#### `sse_provider_requests_total`
**Type**: Counter
**Labels**: `provider`, `status`
**Description**: Requests to each LLM provider

**Design Decision**: Separate from Application Requests
- **Rationale**: One app request may try multiple providers (failover)
- **Mechanism**:
  ```python
  # Application request
  app_requests.labels(status='success').inc()
  
  # Provider requests (may be multiple)
  provider_requests.labels(provider='openai', status='error').inc()
  provider_requests.labels(provider='deepseek', status='success').inc()
  ```
- **Benefit**: Track provider reliability independently

**Provider Failover Tracking**:
```promql
# How often do we failover?
sum(rate(sse_provider_requests_total[5m])) by (provider)
```

Expected pattern:
- Primary provider: 80% of requests
- Fallback provider: 20% of requests (when primary fails)

---

### Streaming Metrics

#### `sse_chunks_streamed_total`
**Type**: Counter
**Labels**: `provider`
**Description**: Total SSE chunks sent to clients

**Design Decision**: Track Chunks, Not Bytes
- **Rationale**: Chunks represent user-visible updates
- **Mechanism**: Increment for each SSE event sent
  ```python
  async for chunk in llm_stream:
      yield f"data: {chunk}\n\n"
      chunks_streamed.labels(provider='openai').inc()
  ```
- **Benefit**: Measure streaming throughput

**Chunks per Request**:
```promql
# Average chunks per request
sum(rate(sse_chunks_streamed_total[5m]))
/
sum(rate(sse_requests_total{status="success"}[5m]))
```

Expected: 50-200 chunks per request (depends on response length)

---

## Design Decisions

### 1. Metric Naming Convention

**Decision**: Use `sse_` prefix for all metrics
**Rationale**: 
- Namespace isolation (avoid conflicts)
- Easy filtering in Prometheus
- Clear ownership

**Pattern**: `<namespace>_<name>_<unit>_<suffix>`
- Namespace: `sse`
- Name: `request_duration`
- Unit: `seconds`
- Suffix: `total` (counter), `bucket` (histogram)

**Examples**:
- ✅ `sse_requests_total`
- ✅ `sse_request_duration_seconds`
- ✅ `sse_cache_hits_total`
- ❌ `requests` (no namespace)
- ❌ `sse_request_time` (no unit)

---

### 2. Label Selection Strategy

**Decision**: Use labels for dimensions, not values
**Rationale**: Enable aggregation and filtering

**Good Labels** (low cardinality):
- `status`: success, error, rate_limited (~5 values)
- `provider`: openai, deepseek, gemini (~3 values)
- `tier`: L1, L2 (~2 values)
- `priority`: HIGH, NORMAL, LOW (~3 values)

**Bad Labels** (high cardinality):
- ❌ `user_id`: Unique per user (10,000+ values)
- ❌ `request_id`: Unique per request (millions of values)
- ❌ `query`: Unique text (infinite values)

**Cardinality Impact**:
```
Metric with 3 labels (5 × 3 × 2 values) = 30 time series
Metric with user_id (10,000 values) = 10,000 time series
```

**Memory Usage**:
- Each time series: ~3KB
- 30 time series: 90KB
- 10,000 time series: 30MB
- With 15-day retention: 450MB!

---

### 3. Histogram Bucket Selection

**Decision**: Logarithmic buckets for latency
**Rationale**: More granularity where it matters

**Linear Buckets** (bad for latency):
```python
buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
# Problem: No granularity below 1s (where most requests are)
```

**Logarithmic Buckets** (good for latency):
```python
buckets=[0.1, 0.5, 1, 2, 5, 10]
# Benefit: Granular for fast requests, coarse for slow
```

**Custom Buckets for Different Metrics**:
- **Request duration**: `[0.1, 0.5, 1, 2, 5, 10]` (seconds)
- **Stage duration**: `[0.001, 0.01, 0.1, 0.5, 1, 2]` (seconds)
- **Chunk size**: `[10, 50, 100, 500, 1000]` (bytes)

---

### 4. Rate Window Selection

**Decision**: Use 5-minute windows for `rate()`
**Rationale**: Balance responsiveness and noise

**Too Short (1 minute)**:
```promql
rate(sse_requests_total[1m])
# Problem: Noisy, spiky graph
# Benefit: Fast detection of changes
```

**Too Long (15 minutes)**:
```promql
rate(sse_requests_total[15m])
# Problem: Slow to react to changes
# Benefit: Very smooth graph
```

**Just Right (5 minutes)**:
```promql
rate(sse_requests_total[5m])
# Balance: Smooth enough, responsive enough
```

**When to Adjust**:
- Alerting: Use longer windows (5-10m) to avoid flapping
- Dashboards: Use shorter windows (1-5m) for responsiveness
- Recording rules: Use longer windows (10-15m) for efficiency

---

### 5. Aggregation Strategy

**Decision**: Aggregate at query time, not at collection
**Rationale**: Maximum flexibility

**Anti-Pattern** (pre-aggregated metric):
```python
# Bad: Only total requests, lost per-instance data
total_requests = Counter('sse_total_requests')
```

**Best Practice** (per-instance metric):
```python
# Good: Collect per-instance, aggregate in query
requests = Counter('sse_requests_total')

# Query: Total across all instances
sum(sse_requests_total)

# Query: Per-instance breakdown
sum(sse_requests_total) by (instance)
```

**Benefit**: One metric, multiple views
- Total: `sum(sse_requests_total)`
- By instance: `sum(sse_requests_total) by (instance)`
- By provider: `sum(sse_requests_total) by (provider)`
- By instance AND provider: `sum(sse_requests_total) by (instance, provider)`

---

## Query Patterns

### Rate Calculations

**Pattern**: `rate(counter[time_range])`
**Purpose**: Convert cumulative counter to per-second rate

**Example**:
```promql
# Requests per second
rate(sse_requests_total[5m])

# Errors per second
rate(sse_requests_total{status!="success"}[5m])
```

**How `rate()` Works**:
1. Get counter value now: 1000
2. Get counter value 5 minutes ago: 700
3. Calculate: (1000 - 700) / 300 seconds = 1 req/s

**Handles Counter Resets**:
```
Time 0: counter = 1000
Time 1: app restarts, counter = 0
Time 2: counter = 100

Without reset handling: (100 - 1000) / time = negative! ❌
With reset handling: rate() detects reset, uses 100 / time ✅
```

---

### Percentile Calculations

**Pattern**: `histogram_quantile(quantile, sum(rate(histogram_bucket[time_range])) by (le))`
**Purpose**: Calculate percentiles from histogram

**Example**:
```promql
# P95 latency
histogram_quantile(0.95,
  sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
)
```

**Step-by-Step**:
1. `rate(sse_request_duration_seconds_bucket[5m])`: Samples per second in each bucket
2. `sum(...) by (le)`: Aggregate across instances, keep bucket labels
3. `histogram_quantile(0.95, ...)`: Interpolate to find 95th percentile

---

### Ratio Calculations

**Pattern**: `numerator / denominator`
**Purpose**: Calculate percentages, rates, ratios

**Example**:
```promql
# Success rate
sum(rate(sse_requests_total{status="success"}[5m]))
/
sum(rate(sse_requests_total[5m]))

# Cache hit rate
sum(rate(sse_cache_hits_total[5m]))
/
(sum(rate(sse_cache_hits_total[5m])) + sum(rate(sse_cache_misses_total[5m])))
```

**Multiply by 100 for Percentage**:
```promql
(...) * 100
```

---

## Best Practices

### 1. Use Recording Rules for Expensive Queries

**Problem**: Complex query runs every dashboard refresh
**Solution**: Pre-compute and store as new metric

**Example**:
```yaml
# prometheus.yml
groups:
  - name: sse_recording_rules
    interval: 30s
    rules:
      - record: sse:request_rate:5m
        expr: sum(rate(sse_requests_total[5m]))
      
      - record: sse:p95_latency:5m
        expr: histogram_quantile(0.95, sum(rate(sse_request_duration_seconds_bucket[5m])) by (le))
```

**Usage**:
```promql
# Instead of complex query
histogram_quantile(0.95, sum(rate(sse_request_duration_seconds_bucket[5m])) by (le))

# Use pre-computed metric
sse:p95_latency:5m
```

**Benefits**:
- Faster dashboard loading
- Reduced Prometheus CPU usage
- Consistent calculations across dashboards

---

### 2. Avoid High-Cardinality Labels

**Bad**:
```python
requests.labels(user_id=user.id).inc()  # ❌ 10,000+ unique values
```

**Good**:
```python
requests.labels(user_tier=user.tier).inc()  # ✅ 3 unique values (free, premium, enterprise)
```

---

### 3. Use Consistent Units

**Time**: Always use seconds (not milliseconds)
```python
request_duration_seconds  # ✅
request_duration_ms       # ❌
```

**Size**: Always use bytes (not KB/MB)
```python
response_size_bytes  # ✅
response_size_kb     # ❌
```

**Rationale**: Prometheus functions expect base units

---

### 4. Document Metrics

**In Code**:
```python
requests_total = Counter(
    'sse_requests_total',
    'Total number of requests processed. '
    'Labels: status (success/error), provider (openai/deepseek/gemini), '
    'model (gpt-4/gpt-3.5/etc), priority (HIGH/NORMAL/LOW)',
    ['status', 'provider', 'model', 'priority']
)
```

**In Grafana**:
- Panel descriptions
- Dashboard annotations
- Variable descriptions

---

### 5. Test Metrics Locally

**Expose Metrics Endpoint**:
```bash
curl http://localhost:8000/admin/metrics
```

**Verify Format**:
```
# HELP sse_requests_total Total number of requests
# TYPE sse_requests_total counter
sse_requests_total{status="success",provider="openai",model="gpt-4",priority="NORMAL"} 42
```

**Check Prometheus**:
```bash
# Query Prometheus
curl 'http://localhost:9090/api/v1/query?query=sse_requests_total'
```

---

## Summary

**Key Design Decisions**:
1. **Histogram for latency**: Enables percentile calculations
2. **Two-tier cache tracking**: Separate L1/L2 for optimization
3. **Rich labels**: Multi-dimensional analysis
4. **5-minute rate windows**: Balance responsiveness and smoothing
5. **Per-instance collection**: Aggregate at query time

**Metric Hierarchy**:
```
Application Metrics (RED Method)
├── Rate: sse_requests_total
├── Errors: sse_requests_total{status!="success"}
└── Duration: sse_request_duration_seconds

Supporting Metrics
├── Cache: sse_cache_hits_total, sse_cache_misses_total
├── Circuit Breaker: sse_circuit_breaker_state
├── Provider: sse_provider_requests_total
└── Streaming: sse_chunks_streamed_total
```

**Query Patterns**:
- Rate: `rate(counter[5m])`
- Percentile: `histogram_quantile(0.95, sum(rate(histogram_bucket[5m])) by (le))`
- Ratio: `numerator / denominator * 100`

**Best Practices**:
- Use recording rules for expensive queries
- Avoid high-cardinality labels
- Use consistent units (seconds, bytes)
- Document metrics thoroughly
- Test locally before deploying
