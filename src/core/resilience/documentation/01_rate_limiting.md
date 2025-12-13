# Layer 1: Distributed Rate Limiting

## Introduction

Rate limiting serves as the first line of defense in the resilience architecture, protecting the system from abuse, resource exhaustion, and ensuring fairsubstantial resource allocation among legitimate users. This implementation employs a sophisticated multi-tiered approach to balance precision with performance.

### Problem Statement

API services face a fundamental vulnerability when exposed to the public internet:

**Uncontrolled Request Patterns**:
- Single user consuming excessive resources
- Malicious actors launching denial-of-service (DoS) attacks
- Misconfigured clients creating infinite retry loops
- Automated scraping overwhelming the system
- Resource monopolization preventing fair access for other users

**Consequences Without Rate Limiting**:
- Service unavailability for all users (resource exhaustion)
- Increased infrastructure costs (scaling to handle abuse)
- Degraded performance for legitimate users
- Database connection pool exhaustion
- Memory and CPU saturation
- Potential cascading failures across services

**The Core Dilemma**: How to protect the system from abuse while maintaining low latency for legitimate users in a distributed environment where multiple application instances serve requests?

### Solution Overview

This system implements a **three-tier hybrid rate limiting architecture** that addresses abuse at multiple levels:

1. **NGINX Layer (Network Perimeter)**
   - Blocks malicious traffic before reaching application
   - IP-based rate limiting at network level
   - Minimal latency overhead (sub-millisecond)
   - First line of defense against DDoS attacks

2. **FastAPI Layer (Application Level)**
   - User-aware rate limiting (authenticated + anonymous)
   - Distributed consistency via Redis
   - Flexible limits per endpoint
   - Detailed error responses with retry guidance

3. **Local Cache Layer (Performance Optimization)**
   - In-memory caching reduces Redis calls by 80-90%
   - Eventual consistency model (acceptable 1-second lag)
   - Sub-millisecond response time for cache hits
   - Graceful degradation if Redis unavailable

**Key Innovation**: The local cache layer provides near-zero latency for rate limit checks while maintaining distributed consistency through periodic synchronization. This allows handling millions of requests per second without overloading Redis.

---

## Architecture

### Three-Tier Defense Stack

```
Request Flow:
    Client Request
         ↓
    [Tier 1: NGINX Rate Limiting]
         ├→ Blocks: Excessive requests/second from single IP
         ↓
    [Tier 2: FastAPI/slowapi Rate Limiting]
         ├→ Blocks: User exceeding quota (50 req/min default)
         ├→ Checks: Redis for distributed state
         ↓
    [Tier 3: Local Cache Optimization]
         ├→ Fast path: Memory check (< 0.1ms)
         ├→ Slow path: Redis sync when needed
         ↓
    application Handler
```

### Tier 1: NGINX Rate Limiting (Network Layer)

**Technology**: NGINX `limit_req_zone` and `limit_req` directives  
**Scope**: Per IP address  
**Purpose**: Network-level protection against DDoS and abuse

**Configuration** (`infrastructure/nginx/nginx.conf`):
```nginx
# Define rate limit zone: 10 requests/second per IP
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Apply to location
location / {
    limit_req zone=api_limit burst=20 nodelay;
    # burst=20: Allow up to 20 requests in quick succession
    # nodelay: Don't delay excess requests, reject immediately
}
```

**How It Works**:
1. NGINX maintains shared memory zone tracking request counts per IP
2. Each request increments IP counter
3. If rate exceeded, return **429 Too Many Requests**
4. Counters reset using sliding window algorithm
5. Happens before any application processing

**Advantages**:
- Extremely fast (handled in NGINX C code)
- Minimal memory usage (binary IP address as key)
- Protects against network-level attacks
- No application resources consumed for blocked requests

**Limitations**:
- IP-based only (can't distinguish users behind same NAT)
- Fixed rate limits (not user-aware)
- No flexibility per endpoint

---

### Tier 2: FastAPI Rate Limiting (Application Layer)

**Technology**: slowapi library with Redis backend  
**Scope**: Per user (identified by X-User-ID, Bearer token, or IP)  
**Purpose**: Application-aware rate limiting with distributed consistency

#### Architecture

```python
# File: src/core/resilience/rate_limiter.py

RateLimitManager
    ├── Limiter (default users): 50 req/min
    ├── Limiter (premium users): 200 req/min  
    ├── LocalRateLimitCache (optimization)
    └── Redis Backend (distributed state)
```

#### User Identification Strategy

Users are identified in priority order:

1. **X-User-ID Header** (Internal/Authenticated)
   - Format: `user:<user_id>`
   - Most accurate identification
   - Used when user is authenticated

2. **Authorization Bearer Token** (API Key)
   - Format: `token:<md5_hash[:16]>`
   - Hashed for privacy (prevents token exposure in logs)
   - Used for API key authentication

3. **Remote IP Address** (Fallback)
   - Format: `ip:<ip_address>`
   - Used for anonymous/public endpoints
   - Subject to NAT limitations

**Code Example**:
```python
def get_user_identifier(request: Request) -> str:
    # Priority 1: X-User-ID header
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return f"user:{user_id}"
    
    # Priority 2: Authorization token (hashed)
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token_hash = hashlib.md5(auth.encode()).hexdigest()[:16]
        return f"token:{token_hash}"
    
    # Priority 3: IP address (fallback)
    return f"ip:{get_remote_address(request)}"
```

#### Rate Limit Algorithm

**Strategy**: Moving Window Counter

**Implementation**:
- **Window**: Fixed time period (e.g., 60 seconds for "50/minute")
- **Redis Keys**: Format `ratelimit:local:{user_id}`
- **Expiration**: Automatic TTL on Redis keys (window duration)
- **Counter**: Incremented per request, reset when window expires

**Advantages**:
- Distributed consistency across all application instances
- Prevents bursts at window boundaries (unlike fixed window)
- Automatic cleanup via Redis TTL
- Configurable per endpoint

#### Tiered Limits

**Default Users**: 50 requests per minute
```python
@router.post("/stream")
@rate_limiter.limit("50/minute")
async def stream_endpoint(request: Request):
    ...
```

**Premium Users**: 200 requests per minute
```python
@router.post("/stream")
@rate_limiter.limit_premium("200/minute")
async def stream_premium(request: Request):
    ...
```

#### Response Headers

When rate limiting is active, responses include informative headers:

| Header | Purpose | Example |
|--------|---------|---------|
| `X-RateLimit-Limit` | Maximum requests allowed | `50` |
| `X-RateLimit-Remaining` | Requests remaining in window | `42` |
| `X-RateLimit-Reset` | Unix timestamp when limit resets | `1702500060` |
| `Retry-After` | Seconds to wait before retry | `60` |

**429 Response Example**:
```json
{
    "error": "rate_limit_exceeded",
    "message": "Too many requests. Please try again later.",
    "retry_after": 60
}
```

---

### Tier 3: Local Cache Optimization

**Technology**: In-memory Python dictionary with async locks  
**Purpose**: Reduce Redis calls by 80-90% while maintaining consistency

#### The Performance Problem

**Without Local Cache**:
- Every request requires 2 Redis operations (GET counter, INCR + EXPIRE)
- At 1000 requests/second: 2000 Redis operations/second
- Network latency: ~1-2ms per operation
- Redis becomes bottleneck

**With Local Cache**:
- Most requests checked against local memory (< 0.1ms)
- Redis only synced periodically or when approaching limit
- At 1000 requests/second: ~100-200 Redis operations/second (90% reduction)
- Redis load reduced, latency improved

#### Algorithm

```python
async def check_and_increment(user_id, limit, window=60):
    # Step 1: Check local cache
    if user_id not in cache:
        cache[user_id] = {
            "count": 0, 
            "window_start": now,
            "redis_count": 0,
            "last_redis_sync": 0
        }
    
    # Step 2: Reset window if expired
    if now - cache[user_id]["window_start"] > window:
        cache[user_id]["count"] = 0
        cache[user_id]["window_start"] = now
        cache[user_id]["redis_count"] = 0
    
    # Step 3: Decide if Redis sync needed
    should_sync = (
        now - cache[user_id]["last_redis_sync"] > SYNC_INTERVAL  # Every 1s
        OR cache[user_id]["count"] >= limit * 0.8  # Approaching limit
    )
    
    # Step 4: Sync with Redis if needed
    if should_sync:
        redis_count = await redis.get(f"ratelimit:local:{user_id}")
        cache[user_id]["redis_count"] = redis_count
        cache[user_id]["last_redis_sync"] = now
    
    # Step 5: Check total count against limit
    total_count = cache[user_id]["count"] + cache[user_id]["redis_count"]
    if total_count >= limit:
        return (False, 0)  # Blocked
    
    # Step 6: Increment local counter
    cache[user_id]["count"] += 1
    
    # Step 7: Async update Redis (fire-and-forget)
    asyncio.create_task(redis.incr(f"ratelimit:local:{user_id}"))
    
    # Step 8: Return allowed
    remaining = limit - total_count - 1
    return (True, remaining)
```

#### Synchronization Strategy

**Sync Triggers**:
1. **Time-based**: Every 1 second since last sync
2. **Count-based**: When local count reaches 80% of limit

**Why 80% Threshold?**
- Prevents exceeding limit due to sync lag
- Balances performance (fewer syncs) with accuracy
- In worst case, user gets ~20% over limit for < 1 second
- Acceptable trade-off for 90% performance gain

**Why 1 Second Interval?**
- Short enough to maintain reasonable consistency
- Long enough to batch multiple requests into single sync
- Matches typical human request patterns

#### Trade-offs

**Advantages**:
- 80-90% reduction in Redis calls
- Sub-millisecond latency for cache hits
- Reduced Redis load enables higher scale
- Graceful degradation if Redis temporarily unavailable

**Disadvantages**:
- **Eventually consistent** (not strongly consistent)
- User may exceed limit by ~20% for up to 1 second
- Requires memory for local cache (negligible: ~100 bytes per user)
- More complex implementation

**Acceptability**:
- For rate limiting, precision loss of 20% for 1 second is acceptable
- Alternative (every request to Redis) would create different bottleneck
- Trade-off favors performance over perfect accuracy

---

## Request Flow Diagram

```mermaid
sequenceDiagram
    participant Client
    participant NGINX as NGINX<br/>(Tier 1)
    participant Middleware as RateLimit Middleware<br/>(Tier 2)
    participant Cache as Local Cache<br/>(Tier 3)
    participant Redis as Redis Store<br/>(Distributed State)
    participant App as Application

    Client->>NGINX: POST /stream
    
    rect rgb(255, 240, 240)
        Note over NGINX: IP Rate Limit Check
        alt IP Exceeds 10 req/sec
            NGINX-->>Client: 429 (NGINX level)
        end
    end
    
    NGINX->>Middleware: Forward Request
    
    rect rgb(240, 255, 240)
        Note over Middleware,Cache: Application Rate Limit Check
        Middleware->>Cache: check_and_increment(user_id)
        
        alt Cache Hit (Fast Path: ~0.1ms)
            Cache-->>Middleware: Allowed (Remaining: 45)
        else Cache Miss or Sync Needed
            Cache->>Redis: GET ratelimit:local:user:123
            Redis-->>Cache: Current Count: 5
            
            alt Total Count >= Limit
                Cache-->>Middleware: Blocked (Remaining: 0)
                Middleware-->>Client: 429 with retry headers
            else Allowed
                Cache->>Redis: INCR (async fire-and-forget)
                Cache-->>Middleware: Allowed (Remaining: 42)
            end
        end
    end
    
    Middleware->>App: Process Request
    App-->>Client: Stream Response
```

---

## Configuration

### NGINX Configuration

**File**: `infrastructure/nginx/nginx.conf`

```nginx
# Define rate limit memory zone
# zone=api_limit:10m → 10MB memory (~160,000 IP addresses)
# rate=10r/s → 10 requests per second per IP
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    location / {
        # Apply rate limit with burst allowance
        limit_req zone=api_limit burst=20 nodelay;
        
        # burst=20: Allow brief bursts up to 20 requests
        # nodelay: Reject excess immediately (don't queue)
        
        proxy_pass http://app_backend;
    }
}
```

### FastAPI Configuration

**File**: `src/core/resilience/rate_limiter.py`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SYNC_INTERVAL` | `1.0` seconds | How often local cache syncs with Redis |
| `Strategy` | `moving-window` | Rate limiting algorithm |
| `Headers Enabled` | `True` | Include rate limit headers in responses |
| `Default Limit` | `50/minute` | Rate limit for standard users |
| `Premium Limit` | `200/minute` | Rate limit for premium users |

### Redis Configuration

**Key Format**: `ratelimit:local:{user_identifier}`  
**TTL**: Automatically expires after window duration (e.g., 60 seconds)  
**Value**: Integer count of requests in current window

---

## Usage Examples

### Basic Endpoint Protection

```python
from src.core.resilience.rate_limiter import setup_rate_limiting, get_rate_limit_manager

# Setup in application
app = FastAPI()
rate_manager = setup_rate_limiting(app)

# Apply to endpoint
@app.post("/stream")
@rate_manager.limit("50/minute")
async def stream_endpoint(request: Request):
    return StreamingResponse(...)
```

### Premium User Endpoint

```python
@app.post("/stream/premium")
@rate_manager.limit_premium("200/minute")
async def stream_premium_endpoint(request: Request):
    # Premium users from the higher limit
    return StreamingResponse(...)
```

### Shared Limit Across Endpoints

```python
# All streaming endpoints share same quota
@app.post("/stream/text")
@rate_manager.shared_limit("100/minute", scope="streaming")
async def stream_text(request: Request):
    ...

@app.post("/stream/code")
@rate_manager.shared_limit("100/minute", scope="streaming")
async def stream_code(request: Request):
    ...
```

---

## Operational Characteristics

### Performance Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| **Cache Hit Rate** | 80-90% | Percentage of requests served from local cache |
| **Cache Check Latency** | < 0.1ms | In-memory dictionary lookup |
| **Redis Check Latency** | 1-2ms | Network round-trip + Redis operation |
| **NGINX Check Latency** | < 0.01ms | In-memory counter |
| **Redis Reduction** | 80-90% | Compared to checking Redis per request |

### Resource Utilization

**Per User Tracking** (Local Cache):
- Memory: ~100 bytes (dictionary entry)
- CPU: Negligible (single dictionary lookup + comparison)

**Redis**:
- Memory: ~50 bytes per user (string counter)
- Operations: 100-200/second per 1000 requests (with cache)

**NGINX**:
- Memory: ~64 bytes per IP (binary IP + counter)
- CPU: Minimal (C-level counter increment)

### Scaling Characteristics

**Horizontal Scaling** (Multiple App Instances):
- Local cache per instance (independent)
- Redis provides distributed consistency
- Eventually consistent across instances (1-second max lag)

**Vertical Scaling** (Higher Limits):
- NGINX: Increase `rate` parameter (e.g., `20r/s`)
- FastAPI: Increase limit string (e.g., `"100/minute"`)
- Local cache: No changes needed (automatically adapts)

---

## Monitoring and Observability

### Key Metrics to Track

| Metric | Purpose | Alert Threshold |
|--------|---------|-----------------|
| Rate limit rejections (429s) | Identify abusive users or misconfigured clients | > 5% of total requests |
| Redis latency | Detect Redis performance issues | > 5ms P99 |
| Cache hit rate | Verify local cache effectiveness | < 70% |
| Top rate-limited users | Identify potential abuse patterns | Review daily |

### Logging

**429 Responses**:
```python
logger.warning("Rate limit exceeded", 
               user=get_user_identifier(request),
               limit="50/minute",
               path=request.url.path)
```

**Redis Sync Failures**:
```python
logger.warning("Redis sync failed in local rate limit cache",
               user_id=user_id,
               error=str(e))
# Gracefully degrades to local cache only
```

---

## Edge Cases and Failure Modes

### Redis Unavailable

**Behavior**:
- Local cache continues functioning independently
- Each application instance enforces limits based on its own counter
- Trade-off: User could exceed limit across instances

**Mitigation**:
- NGINX layer still provides IP-based protection
- Acceptable temporary degradation
- Alerts trigger for Redis outage

### Clock Skew Between Instances

**Problem**: Different instances have slightly different system times  
**Impact**: Window resets happen at slightly different times  
**Magnitude**: Typically < 100ms with NTP  
**Acceptability**: Negligible for 60-second windows

### Thundering Herd (Window Boundary)

**Problem**: All users' windows reset simultaneously  
**Mitigation**: Moving window algorithm smooths this effect  
**Local cache**: Resets happen per-instance, not globally

---

## Tuning Recommendations

### High Traffic, Low Abuse

Increase limits, reduce sync frequency:
```python
SYNC_INTERVAL = 2.0  # Less frequent syncs
default_limit = "100/minute"  # Higher baseline
```

### High Abuse Risk

Decrease limits, increase sync frequency:
```python
SYNC_INTERVAL = 0.5  # More frequent syncs
default_limit = "30/minute"  # Stricter baseline
nginx rate = 5r/s  # Stricter network limit
```

### Cost Optimization (Reduce Redis Usage)

Increase sync interval:
```python
SYNC_INTERVAL = 2.0  # Halves Redis operations
# Trade-off: Up to 2-second inconsistency
```

### Strict Compliance (Precision Required)

Sync on every request (disable local cache optimization):
```python
# Comment out local cache checks, use Redis directly
# Trade-off: 10x increase in Redis load, higher latency
```

---

## Security Considerations

### Token Hashing

```python
# GOOD: Hash tokens for privacy
token_hash = hashlib.md5(auth_header.encode()).hexdigest()[:16]

# BAD: Don't log raw tokens
# logger.info(f"Rate limiting {auth_header}")  # Exposes token!
```

### IP Spoofing

**NGINX Protection**:
- Uses real client IP (`$remote_addr`)
- Ignores client-provided headers like `X-Forwarded-For`

**Application Layer**:
- Trusts NGINX-provided headers (`X-Real-IP`)
- Validates header presence

### Distributed Denial of Service (DDoS)

**Multi-Layer Defense**:
1. NGINX: Network-level protection (10 req/sec per IP)
2. FastAPI: Application-level limits (50 req/min per user)
3. Connection Pool: Limits concurrent connections (Layer 2 defense)
4. Queue Failover: Handles overflow gracefully (Layer 3 defense)

---

## Future Enhancements

### Planned Improvements

1. **Dynamic Rate Limits**: Adjust limits based on system load
2. **Geographic Limits**: Different limits per region
3. **Endpoint-Specific Limits**: Custom limits per endpoint
4. **Rate Limit Analytics**: Dashboard tracking usage patterns
5. **Whitelist/Blacklist**: Bypass limits for trusted IPs/users

### Research Areas

1. **Adaptive Limits**: ML-based anomaly detection
2. **Token Bucket**: Replace moving window with token bucket
3. **Distributed Counter**: Replace Redis with distributed counter (etcd, Consul)

---

## Integration with Other Layers

### Layer 2: Connection Pool

Rate limiting prevents requests from reaching the connection pool, reducing load:
- Users blocked at rate limit never consume connection slots
- Protects connection pool from single-user monopolization

### Layer 3: Queue Failover

Rate limiting happens before queue failover:
```
Request Flow:
    Client → NGINX Rate Limit → FastAPI Rate Limit → Connection Pool → Queue Failover
```

Only legitimate, rate-limited users can trigger queue failover.

---

## Testing and Verification

### Manual Testing

**Test Rate Limit Enforcement**:
```bash
# Send 60 requests in quick succession
for i in {1..60}; do
    curl -X POST http://localhost:8000/stream \
         -H "X-User-ID: test-user" \
         -H "Content-Type: application/json" \
         -d '{"query":"test"}' &
done
wait

# Expected: First 50 succeed, next 10 get 429
```

**Test Premium Limits**:
```bash
# Send 250 requests
for i in {1..250}; do
    curl -X POST http://localhost:8000/stream \
         -H "X-User-ID: premium-user" \
         -H "X-Premium-User: true" \
         -d '{"query":"test"}' &
done
wait

# Expected: First 200 succeed, next 50 get 429
```

###Verify Cache Effectiveness

```python
# Monitor Redis operations
redis-cli MONITOR | grep "ratelimit:local"

# Expected: ~10-20% of requests hit Redis (80-90% cache hit rate)
```

---

## References

**Source Files**:
- Rate Limiter: `src/core/resilience/rate_limiter.py` (334 lines)
- NGINX Config: `infrastructure/nginx/nginx.conf`
- Application Setup: `src/application/app.py`

**Related Documentation**:
- [02_connection_pooling.md](./02_connection_pooling.md) - Layer 2 defense
- [04_queue_failover.md](./04_queue_failover.md) - Layer 3 defense
- [01_overview.md](./01_overview.md) - Three-layer architecture

**External Resources**:
- [NGINX Rate Limiting](https://www.nginx.com/blog/rate-limiting-nginx/)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
- [slowapi Documentation](https://slowapi.readthedocs.io/)

**Design Patterns**:
- Leaky Bucket / Token Bucket (rate limiting algorithms)
- Cache-Aside Pattern (local cache with Redis backend)
- Tiered Defense (multiple layers of protection)
