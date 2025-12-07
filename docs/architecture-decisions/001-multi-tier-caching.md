# ADR-001: Multi-Tier Caching Strategy (L1 + L2)

**Status**: Accepted  
**Date**: 2025-12-05  
**Decision Makers**: System Architect  
**Tags**: #caching #performance #infrastructure

## Context

LLM API calls are expensive in both cost and latency:
- **Cost**: $0.002 per 1K tokens (OpenAI GPT-3.5)
- **Latency**: 100-5000ms per request
- **Scale**: 10,000+ requests/minute expected at peak

Without caching, identical queries would hit the LLM API repeatedly, resulting in:
- Unnecessary API costs (~$2000/month for duplicate queries)
- Poor user experience (slow response times)
- Wasted compute resources

We need aggressive caching to minimize redundant calls, but caching introduces complexity:
- **Where to cache?** (memory vs. distributed)
- **How long to cache?** (TTL strategy)
- **How to handle cache failures?** (graceful degradation)

## Decision

Implement **two-tier caching** (L1 + L2) working together:

### L1: In-Memory LRU Cache
- **Location**: Application memory (`OrderedDict`)
- **Size**: 1,000 entries (configurable via `CACHE_L1_MAX_SIZE`)
- **Access Time**: < 1ms
- **Persistence**: None (lost on restart)
- **Sharing**: Per-instance (not shared across pods)
- **Use Case**: **Hot data** - frequently accessed within short time window

### L2: Redis Distributed Cache
- **Location**: Redis cluster (external)
- **Size**: Limited by Redis memory (~10GB)
- **Access Time**: 1-5ms (network round-trip)
- **Persistence**: Survives restarts (Redis persistence enabled)
- **Sharing**: Shared across all instances
- **Use Case**: **Warm data** - shared across instances, longer time windows

## Algorithm: Cache-Aside Pattern

### Read Flow
```
1. Check L1 cache → if HIT, return (< 1ms)
2. Check L2 cache → if HIT, warm L1, return (1-5ms)
3. Call LLM API → cache in L1 and L2, return (100-5000ms)
```

### Write Flow
```
1. Write to L1 (synchronous)
2. Write to L2 (asynchronous via pipeline)
```

### Visual Diagram
```
┌─────────────┐
│   Request   │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  L1 (Memory)    │ ◄─── < 1ms
│  LRU Cache      │
└────┬────────────┘
     │ MISS
     ▼
┌─────────────────┐
│  L2 (Redis)     │ ◄─── 1-5ms
│  Distributed    │
└────┬────────────┘
     │ MISS
     ▼
┌─────────────────┐
│  LLM API        │ ◄─── 100-5000ms
│  (OpenAI, etc)  │
└─────────────────┘
```

## Consequences

### ✅ Pros
1. **95%+ cache hit rate** (L1 handles hot, L2 handles warm)
2. **Sub-millisecond latency** for popular queries (L1)
3. **Cross-instance sharing** (L2 prevents duplicate API calls)
4. **Graceful degradation** (if Redis fails, L1 still works)
5. **Cost savings**: ~95% reduction in LLM API calls

### ⚠️ Cons
1. **Increased complexity** (two cache tiers to manage)
2. **Memory overhead** (L1 + Redis)
3. **Cache coherency challenges** (L1 may be stale vs. L2)
4. **Additional infrastructure** (Redis cluster required)

## Alternatives Considered

### Alternative 1: Single-tier Redis only
- **Rejected**: 1-5ms latency for every request (vs. <1ms with L1)
- **Analysis**: Network round-trip overhead adds up at scale

### Alternative 2: Single-tier memory only
- **Rejected**: No sharing across instances (wasted duplicate calls)
- **Analysis**: Each pod would make its own LLM calls for same queries

### Alternative 3: Write-through caching
- **Rejected**: Increases write latency (L2 write is synchronous)
- **Analysis**: Async write to L2 is acceptable (eventual consistency)

## Performance Metrics

### Expected Performance
- **L1 hit rate**: ~60-70% (hot data)
- **L2 hit rate**: ~25-30% (warm data)
- **Combined hit rate**: ~95%
- **Latency reduction**: 50-90% (vs. always calling LLM)
- **Cost savings**: ~95% (only 5% of requests hit LLM API)

### Memory Usage
- **L1**: ~200 KB (1,000 entries × 200 bytes avg)
- **L2**: ~2 GB (10M entries × 200 bytes avg)
- **Total per instance**: ~200 KB + shared Redis

## Monitoring

Track these metrics to validate strategy:
```python
# Prometheus metrics
cache_hits_total{tier="L1"}
cache_hits_total{tier="L2"}
cache_miss_total
cache_latency_seconds{tier="L1"}
cache_latency_seconds{tier="L2"}
cache_size{tier="L1"}
cache_evictions_total{tier="L1"}
```

## Implementation

- **File**: `src/infrastructure/cache/cache_manager.py`
- **Classes**: `LRUCache`, `CacheManager`
- **Configuration**: `settings.cache.CACHE_L1_MAX_SIZE`, `CACHE_RESPONSE_TTL`

## Related ADRs

- ADR-002: Redis connection pooling strategy
- ADR-003: Cache TTL optimization
- ADR-004: Cache warming for popular items

## References

- [Cache-Aside Pattern](https://docs.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
- [Redis Best Practices](https://redis.io/docs/manual/patterns/)
- [LRU Cache Algorithm](https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU))
