# ADR-005: Queue Backpressure and Load Shedding

**Status**: Accepted
**Date**: 2025-12-05
**Decision Makers**: System Architect
**Tags**: #resilience #backpressure #load-shedding #queues #redis #kafka

## Context

In distributed systems using message queues for background processing, queues can become overwhelmed:

### Problems Without Backpressure/Load Shedding

**Silent Message Loss**: Redis Streams automatically trim old messages when `maxlen` is reached, causing unnoticed data loss of analytics events, logs, and background jobs.

**System Overload**: Producers keep sending messages even when consumers can't keep up, leading to:
- Memory exhaustion in Redis/Kafka
- Consumer backlogs growing indefinitely
- System performance degradation
- Cascading failures across the entire system

**No Visibility**: Without monitoring queue depth and backpressure metrics, operators can't detect when queues are approaching capacity.

**Resource Waste**: Failed message production attempts waste CPU, network, and memory resources without any benefit.

### Business Impact

- **Data Loss**: Analytics events and logs disappear silently
- **Poor User Experience**: System becomes slow/unresponsive under load
- **Operational Issues**: Hard to debug why background jobs aren't processing
- **Cost Inefficiency**: Wasted infrastructure resources on failed operations

## Decision

Implement **hybrid backpressure and load shedding** using `aioresilience` library with queue-specific optimizations:

### Two-Tier Protection Strategy

```
┌─────────────────┐    ┌──────────────────┐
│  Load Shedding  │───▶│   Backpressure   │
│ (Request Level) │    │  (Queue Level)   │
└─────────────────┘    └──────────────────┘
        │                        │
        ▼                        ▼
 ┌──────────────┐        ┌──────────────┐
 │Reject Excess │        │Retry with    │
 │Requests      │        │Exponential   │
 │Early         │        │Backoff       │
 └──────────────┘        └──────────────┘
```

#### 1. Load Shedding (Request-Level Protection)

**When**: Applied before queue operations
**How**: `aioresilience.BasicLoadShedder` limits request rate
**Threshold**: Configurable max requests per time window
**Behavior**: Rejects new requests with `QueueFullError` when threshold exceeded

#### 2. Backpressure (Queue-Level Protection)

**When**: Applied when queues approach capacity
**How**: Monitor queue depth and apply exponential backoff retry
**Threshold**: Configurable percentage of max queue depth (default: 80%)
**Behavior**: Wait/retry with jitter to prevent thundering herd

### Implementation by Queue Type

#### Redis Streams Implementation

```python
# Check queue depth before producing
stream_length = await redis.xlen(stream_name)

# Load shedding first
if not await load_shedder.accept():
    raise QueueFullError("Load shedding active")

# Backpressure if approaching capacity
if stream_length >= threshold:
    await retry_with_exponential_backoff(produce_message)
```

**Key Features**:
- Real-time stream length monitoring with `XLEN`
- Automatic trimming with `MAXLEN` (prevents infinite growth)
- Consumer group support for load balancing

#### Kafka Implementation

```python
# Configure producer with backpressure settings
producer = AIOKafkaProducer(
    buffer_memory=32MB,           # Natural backpressure
    max_in_flight_requests=5      # Connection-level limiting
)

# Load shedding before producing
if not await load_shedder.accept():
    raise QueueFullError("Load shedding active")

# Handle buffer-full errors
try:
    await producer.send(topic, message)
except KafkaError as e:
    if "buffer" in str(e).lower():
        raise QueueFullError("Kafka buffer full")
```

**Key Features**:
- Built-in producer buffer management
- Partition-based load balancing
- Configurable buffer memory limits

### Configuration Parameters

```python
# Backpressure settings
QUEUE_MAX_DEPTH = 10000              # Max messages per queue
QUEUE_BACKPRESSURE_THRESHOLD = 0.8   # 80% capacity trigger
QUEUE_BACKPRESSURE_MAX_RETRIES = 3   # Retry attempts
QUEUE_BACKPRESSURE_BASE_DELAY = 0.1  # Base backoff delay

# Load shedding settings
QUEUE_LOAD_SHEDDING_ENABLED = True
QUEUE_LOAD_SHEDDING_MAX_REQUESTS = 1000  # Per time window

# Kafka-specific
KAFKA_BUFFER_MEMORY = 33554432       # 32MB buffer
KAFKA_MAX_IN_FLIGHT_REQUESTS = 5     # Connection limit
```

## Consequences

### Positive Outcomes

**Reliability**:
- ✅ Prevents silent message loss in Redis Streams
- ✅ Protects system from queue-related memory exhaustion
- ✅ Maintains service availability under load spikes

**Observability**:
- ✅ Comprehensive metrics for queue depth and backpressure events
- ✅ Structured logging with `QUEUE.*` stages for debugging
- ✅ Prometheus integration for monitoring dashboards

**Performance**:
- ✅ Exponential backoff prevents thundering herd problems
- ✅ Load shedding provides graceful degradation
- ✅ Configurable thresholds adapt to different environments

**Operational**:
- ✅ Early warning when queues approach capacity
- ✅ Configurable behavior via environment variables
- ✅ No code changes needed for threshold tuning

### Negative Outcomes

**Complexity**:
- ⚠️ Additional configuration parameters to manage
- ⚠️ More metrics to monitor and alert on
- ⚠️ Retry logic adds latency for failed operations

**Resource Usage**:
- ⚠️ Queue length checks add Redis/Kafka round-trips
- ⚠️ Metrics collection has small performance overhead
- ⚠️ Load shedder state consumes memory

**Operational Overhead**:
- ⚠️ More environment variables to configure
- ⚠️ Additional Prometheus metrics to monitor
- ⚠️ Tuning thresholds requires domain knowledge

## Alternatives Considered

### Alternative 1: Built-in Queue Features Only

**Approach**: Rely solely on Redis `maxlen` trimming and Kafka buffer limits
**Pros**: Simple, zero additional dependencies, automatic
**Cons**: Silent message loss, no load shedding, poor observability
**Decision**: Rejected - unacceptable data loss and lack of control

### Alternative 2: Custom Implementation

**Approach**: Build custom load shedding and backpressure from scratch
**Pros**: Full control, tailored to our needs
**Cons**: High development cost, maintenance burden, testing complexity
**Decision**: Rejected - `aioresilience` provides proven patterns

### Alternative 3: Synchronous Processing

**Approach**: Process background tasks synchronously instead of queuing
**Pros**: No queue management, simpler architecture
**Cons**: Blocks main request path, poor scalability, no decoupling
**Decision**: Rejected - violates async processing requirements

### Alternative 4: External Queue Proxies

**Approach**: Use tools like Envoy or NGINX for queue proxying with backpressure
**Pros**: Off-the-shelf solution, battle-tested
**Cons**: Additional infrastructure, configuration complexity, vendor lock-in
**Decision**: Rejected - overkill for current scale, adds operational complexity

## Metrics & Monitoring

### Key Metrics

**Queue Health Metrics**:
- `sse_queue_depth{queue_name}` - Current queue depth
- `sse_queue_produce_attempts_total{queue_type}` - Production attempts
- `sse_queue_produce_success_total{queue_type}` - Successful productions
- `sse_queue_produce_failures_total{queue_type,reason}` - Failures by reason

**Backpressure Metrics**:
- `sse_queue_backpressure_retries_total{queue_type}` - Retry attempts

### Alerting Rules

```yaml
# High queue depth warning
- alert: QueueApproachingCapacity
  expr: sse_queue_depth > 8000  # 80% of 10k
  for: 5m
  labels:
    severity: warning

# Queue at capacity (critical)
- alert: QueueAtCapacity
  expr: sse_queue_depth >= 10000
  for: 1m
  labels:
    severity: critical

# High backpressure retry rate
- alert: HighBackpressureRate
  expr: rate(sse_queue_backpressure_retries_total[5m]) > 10
  for: 2m
  labels:
    severity: warning
```

### Monitoring Dashboards

**Grafana Panels**:
- Queue depth over time by queue name
- Backpressure retry rate trends
- Load shedding activation frequency
- Queue throughput (produces/consumes per second)

## Implementation Details

### Code Structure

```
src/
├── core/
│   ├── config/
│   │   ├── settings.py          # QueueSettings class
│   │   └── constants.py         # Queue constants
│   └── exceptions/
│       └── base.py              # QueueFullError
├── infrastructure/
│   ├── message_queue/
│   │   ├── redis_queue.py       # Backpressure + load shedding
│   │   ├── kafka_queue.py       # Buffer config + load shedding
│   │   └── factory.py           # Queue instantiation
│   └── monitoring/
│       └── metrics_collector.py # Queue metrics
```

### Error Handling

**QueueFullError**: Raised when queues are full or load shedding is active
- Includes queue name, current depth, max depth
- Different reasons: "load_shedding", "buffer_full", "queue_full"
- Allows callers to implement custom retry logic

**Logging Stages**:
- `QUEUE.BACKPRESSURE` - When backpressure is applied
- `QUEUE.LOAD_SHEDDING` - When load shedding rejects requests
- `QUEUE.RETRY` - Backpressure retry attempts
- `QUEUE.WARNING` - Approaching capacity warnings

### Testing Strategy

**Unit Tests**:
- Backpressure retry logic with mocked Redis/Kafka
- Load shedding threshold behavior
- Error handling and metrics recording

**Integration Tests**:
- Full queue scenarios with real Redis/Kafka
- Load shedding under concurrent requests
- Metrics collection verification

**Performance Tests**:
- Backpressure impact on throughput
- Memory usage with large queues
- CPU overhead of queue monitoring

## Migration & Rollout

### Zero-Downtime Deployment

1. **Phase 1**: Deploy with load shedding disabled, backpressure enabled
   - Monitor queue behavior with new metrics
   - Tune backpressure thresholds

2. **Phase 2**: Enable load shedding with conservative thresholds
   - Monitor rejection rates
   - Adjust based on business requirements

3. **Phase 3**: Optimize thresholds for production load
   - Fine-tune based on observed patterns
   - Set up alerting and dashboards

### Configuration Migration

```bash
# Old configuration (no backpressure)
QUEUE_MAX_DEPTH=10000

# New configuration (with backpressure)
QUEUE_MAX_DEPTH=10000
QUEUE_BACKPRESSURE_THRESHOLD=0.8
QUEUE_BACKPRESSURE_MAX_RETRIES=3
QUEUE_LOAD_SHEDDING_ENABLED=true
QUEUE_LOAD_SHEDDING_MAX_REQUESTS=1000
```

### Rollback Plan

- Disable load shedding: `QUEUE_LOAD_SHEDDING_ENABLED=false`
- Increase backpressure thresholds: `QUEUE_BACKPRESSURE_THRESHOLD=0.95`
- Revert to built-in queue limits only if needed

## Future Considerations

### Enhancements

**Adaptive Thresholds**: Automatically adjust thresholds based on system load
**Priority Queues**: Different backpressure behavior for high/low priority messages
**Cross-Queue Coordination**: Coordinate backpressure across multiple queues

### Scaling Considerations

**Multi-Instance Coordination**: Share backpressure state across instances
**Queue Sharding**: Distribute load across multiple queue instances
**External Monitoring**: Integration with APM tools like DataDog/New Relic

## Summary

This decision implements production-ready queue backpressure and load shedding that:

- **Prevents data loss** through explicit capacity management
- **Maintains system stability** under load with graceful degradation
- **Provides full observability** through comprehensive metrics and logging
- **Minimizes operational complexity** with sensible defaults and configuration

The hybrid approach balances effectiveness with maintainability, using proven libraries (`aioresilience`, `tenacity`) while maintaining compatibility with existing Redis and Kafka infrastructure.</content>
</xai:function_call">Now I need to update the README.md file to include this new ADR in the list. Let me check the current README and add the new entry. 

<xai:function_call name="search_replace">
<parameter name="file_path">docs/architecture-decisions/README.md












