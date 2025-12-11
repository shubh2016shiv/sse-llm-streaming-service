# ADR 020: API Versioning Strategy with URL Path Prefix

## Status

**Accepted** - 2025-12-11

## Context

The SSE streaming microservice is a production API that will evolve over time with new features, bug fixes, and breaking changes. The API needs a **versioning strategy** that allows:
- **Backward compatibility**: Old clients continue working
- **Gradual migration**: Clients upgrade at their own pace
- **Clear deprecation**: Sunset old versions gracefully
- **Professional appearance**: Industry-standard URL structure

### Problem Statement

Without versioning, API changes break existing clients:

1. **Breaking Changes Break Clients**: No way to introduce incompatible changes
   ```python
   # V1: query is string
   {"query": "Hello"}
   
   # V2: query is object (BREAKING CHANGE!)
   {"query": {"text": "Hello", "context": "..."}}
   
   # Old clients break when V2 deployed!
   ```

2. **No Migration Path**: Clients forced to upgrade immediately
   - Deploy new API → all clients break
   - No time to test and migrate
   - Downtime and errors

3. **Unclear Deprecation**: No way to sunset old versions
   - Can't remove old code
   - Technical debt accumulates
   - Maintenance burden

4. **Unprofessional URLs**: Root-level endpoints look amateurish
   ```
   ❌ POST /stream (no version)
   ✅ POST /api/v1/stream (versioned)
   ```

### Real-World Impact

**Without Versioning**:
```
Day 1: Deploy API
  POST /stream → {"query": "Hello"}
  
Day 30: Need to change request format (breaking change)
  Problem: Can't deploy without breaking all clients!
  
Options:
  1. Don't make change (technical debt)
  2. Break all clients (downtime)
  3. Add new endpoint /stream-v2 (messy)
```

**With Versioning**:
```
Day 1: Deploy V1
  POST /api/v1/stream → {"query": "Hello"}
  
Day 30: Deploy V2 (breaking change)
  POST /api/v2/stream → {"query": {"text": "Hello"}}
  POST /api/v1/stream → Still works! (backward compatible)
  
Day 60: Clients migrate to V2 at their own pace
  
Day 180: Deprecate V1
  POST /api/v1/stream → 410 Gone (deprecated)
  POST /api/v2/stream → Active
```

### Why This Matters

- **Backward Compatibility**: Old clients keep working
- **Flexibility**: Can introduce breaking changes safely
- **Professionalism**: Industry-standard URL structure
- **Clear Communication**: Version in URL is self-documenting

## Decision

Use **URL path prefix versioning** with `/api/v{N}` format for all API endpoints.

### Visual Architecture

```mermaid
graph TB
    subgraph "URL Structure"
        A[Base URL] --> B[/api]
        B --> C[/v1]
        C --> D[/stream]
        C --> E[/health]
        C --> F[/admin]
        
        B --> G[/v2]
        G --> H[/stream]
        G --> I[/health]
    end
    
    subgraph "Version Lifecycle"
        J[V1: Active] --> K[V2: Released]
        K --> L[V1: Deprecated]
        L --> M[V1: Sunset]
        M --> N[V2: Active Only]
    end
    
    subgraph "Client Migration"
        O[Old Clients] --> P[Use V1]
        Q[New Clients] --> R[Use V2]
        P --> S[Migrate to V2]
        S --> R
    end
    
    style C fill:#51cf66,stroke:#2f9e44
    style G fill:#339af0,stroke:#1971c2
    style L fill:#ffd43b,stroke:#fab005
    style M fill:#ff6b6b,stroke:#c92a2a,color:#fff
```

**Key Components**:
1. **URL Prefix**: `/api/v1`, `/api/v2`, etc.
2. **Version Lifecycle**: Active → Deprecated → Sunset
3. **Parallel Versions**: Multiple versions coexist
4. **Gradual Migration**: Clients upgrade at their own pace

### Implementation Strategy

#### Configuration

```python
# File: src/core/config/settings.py

class AppSettings(BaseSettings):
    """Application settings with API versioning."""
    
    API_BASE_PATH: str = Field(
        default="/api/v1",
        description="API base path with version"
    )
    
    API_VERSION: str = Field(
        default="1.0.0",
        description="API semantic version"
    )
```

#### FastAPI Integration

```python
# File: src/application/app.py

def create_app() -> FastAPI:
    """Create FastAPI application with versioned routes."""
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app.APP_NAME,
        version=settings.app.API_VERSION,
        description="SSE Streaming Microservice"
    )
    
    # Base path includes version
    base_path = settings.API_BASE_PATH  # "/api/v1"
    
    # Register routers with versioned prefix
    app.include_router(health_router, prefix=base_path)
    app.include_router(streaming_router, prefix=base_path)
    app.include_router(admin_router, prefix=base_path)
    
    return app
```

#### Example URLs

```
Production URLs:
  POST   /api/v1/stream          - Create streaming session
  GET    /api/v1/health          - Health check
  GET    /api/v1/admin/metrics   - Admin metrics
  
Documentation:
  GET    /docs                   - Swagger UI
  GET    /redoc                  - ReDoc
  
Root:
  GET    /                       - API information
```

### Versioning Scheme

#### URL Path Versioning (Chosen)

**Format**: `/api/v{major}`

**Examples**:
- `/api/v1/stream` - Version 1
- `/api/v2/stream` - Version 2
- `/api/v3/stream` - Version 3

**Advantages**:
- ✅ **Clear**: Version visible in URL
- ✅ **Cacheable**: Different URLs for different versions
- ✅ **Simple**: Easy to implement and understand
- ✅ **RESTful**: Follows REST principles

**Disadvantages**:
- ⚠️ **URL Changes**: Version change requires URL update
- ⚠️ **Duplication**: Some code duplicated across versions

#### Semantic Versioning

**Format**: `MAJOR.MINOR.PATCH`

**Examples**:
- `1.0.0` - Initial release
- `1.1.0` - New feature (backward compatible)
- `1.1.1` - Bug fix (backward compatible)
- `2.0.0` - Breaking change (not backward compatible)

**URL Mapping**:
- `1.x.x` → `/api/v1`
- `2.x.x` → `/api/v2`
- `3.x.x` → `/api/v3`

**Rules**:
- **MAJOR**: Increment for breaking changes
- **MINOR**: Increment for new features (backward compatible)
- **PATCH**: Increment for bug fixes (backward compatible)

### Version Lifecycle

#### Phase 1: Active

**Status**: Fully supported, recommended for new clients

**Example**:
```
GET /api/v1/stream
Response: 200 OK
```

#### Phase 2: Deprecated

**Status**: Still works, but clients should migrate

**Example**:
```
GET /api/v1/stream
Response: 200 OK
Headers:
  Deprecation: true
  Sunset: 2025-12-31
  Link: </api/v2/stream>; rel="successor-version"
```

**Client sees**:
```
⚠️ Warning: This API version is deprecated
   Migrate to: /api/v2/stream
   Sunset date: 2025-12-31
```

#### Phase 3: Sunset

**Status**: No longer supported, returns error

**Example**:
```
GET /api/v1/stream
Response: 410 Gone
{
  "error": "version_sunset",
  "message": "API v1 has been sunset. Please use v2.",
  "successor_version": "/api/v2/stream",
  "sunset_date": "2025-12-31"
}
```

### Migration Path

#### Step 1: Announce Deprecation

```
Email to API users:
  Subject: API v1 Deprecation Notice
  
  Dear API Users,
  
  API v1 will be deprecated on 2025-10-01 and sunset on 2025-12-31.
  
  Please migrate to v2:
  - Old: POST /api/v1/stream
  - New: POST /api/v2/stream
  
  Changes:
  - Request format updated (see docs)
  - New features available
  
  Migration guide: https://docs.example.com/migration/v1-to-v2
```

#### Step 2: Deprecation Period (3 months)

```python
# V1 endpoints return deprecation headers
@router.post("/stream")
async def stream_v1():
    """V1 stream endpoint (deprecated)."""
    return StreamingResponse(
        ...,
        headers={
            "Deprecation": "true",
            "Sunset": "2025-12-31",
            "Link": "</api/v2/stream>; rel=\"successor-version\""
        }
    )
```

#### Step 3: Sunset (After 3 months)

```python
# V1 endpoints return 410 Gone
@router.post("/stream")
async def stream_v1():
    """V1 stream endpoint (sunset)."""
    return JSONResponse(
        status_code=410,
        content={
            "error": "version_sunset",
            "message": "API v1 has been sunset. Please use v2.",
            "successor_version": "/api/v2/stream",
            "sunset_date": "2025-12-31"
        }
    )
```

## Implementation Details

### Current Version (V1)

```python
# File: src/application/api/routes/streaming.py

router = APIRouter(tags=["Streaming"])

@router.post("/stream")
async def create_stream(
    request: Request,
    body: StreamRequestModel,
    orchestrator: OrchestratorDep,
    user_id: UserIdDep
):
    """
    Create SSE streaming session.
    
    Version: 1.0.0
    Endpoint: POST /api/v1/stream
    """
    # Implementation
    ...
```

### Future Version (V2)

```python
# File: src/application/api/routes/v2/streaming.py

router = APIRouter(tags=["Streaming V2"])

@router.post("/stream")
async def create_stream_v2(
    request: Request,
    body: StreamRequestModelV2,  # New model
    orchestrator: OrchestratorDep,
    user_id: UserIdDep
):
    """
    Create SSE streaming session (V2).
    
    Version: 2.0.0
    Endpoint: POST /api/v2/stream
    
    Changes from V1:
    - New request format
    - Additional features
    """
    # New implementation
    ...
```

### Configuration for Multiple Versions

```python
# File: src/application/app.py

def create_app() -> FastAPI:
    """Create app with multiple API versions."""
    app = FastAPI(...)
    
    # V1 routes (current)
    from src.application.api.routes import streaming as streaming_v1
    app.include_router(streaming_v1.router, prefix="/api/v1")
    
    # V2 routes (future)
    from src.application.api.routes.v2 import streaming as streaming_v2
    app.include_router(streaming_v2.router, prefix="/api/v2")
    
    return app
```

## Consequences

### Positive

1. **Backward Compatibility**: Old clients keep working
   - V1 clients use `/api/v1`
   - V2 clients use `/api/v2`
   - Both coexist

2. **Gradual Migration**: Clients upgrade at their own pace
   - No forced upgrades
   - Time to test and migrate
   - Reduced risk

3. **Clear Deprecation**: Sunset process is transparent
   - Deprecation headers warn clients
   - Sunset date communicated
   - Migration guide provided

4. **Professional URLs**: Industry-standard structure
   - `/api/v1/stream` looks professional
   - Self-documenting
   - Follows REST conventions

5. **Flexibility**: Can introduce breaking changes
   - New features without breaking old clients
   - Technical debt can be addressed
   - Innovation enabled

### Negative

1. **Code Duplication**: Multiple versions = duplicated code
   - **Mitigation**: Share common logic in services
   - **Mitigation**: Only duplicate route handlers
   - **Trade-off**: Duplication vs. backward compatibility

2. **Maintenance Burden**: Must support multiple versions
   - **Mitigation**: Deprecate old versions aggressively
   - **Mitigation**: Maximum 2 active versions at once
   - **Trade-off**: Maintenance vs. compatibility

3. **URL Changes**: Clients must update URLs for new version
   - **Mitigation**: Clear migration guide
   - **Mitigation**: Deprecation period for migration
   - **Acceptable**: Necessary for versioning

### Neutral

1. **Version in URL**: Some prefer header versioning
   - **Acceptable**: URL versioning is more common
   - **Benefit**: More visible and cacheable

## Alternatives Considered

### Alternative 1: Header Versioning

```http
GET /stream
Accept-Version: v1
```

**Rejected**:
- ❌ **Not cacheable**: Same URL for different versions
- ❌ **Less visible**: Version hidden in headers
- ❌ **More complex**: Requires header parsing

### Alternative 2: Query Parameter Versioning

```http
GET /stream?version=1
```

**Rejected**:
- ❌ **Not RESTful**: Version is not a resource property
- ❌ **Optional**: Easy to forget
- ❌ **Ugly URLs**: Query parameters clutter URL

### Alternative 3: Subdomain Versioning

```http
GET https://v1.api.example.com/stream
```

**Rejected**:
- ❌ **DNS complexity**: Need multiple subdomains
- ❌ **SSL certificates**: Need certs for each subdomain
- ❌ **Deployment complexity**: Separate deployments

### Alternative 4: No Versioning

**Rejected**:
- ❌ **Breaking changes break clients**: No migration path
- ❌ **Technical debt**: Can't remove old code
- ❌ **Unprofessional**: Not industry standard

## Best Practices

### 1. Use Major Version in URL

✅ **Good**:
```
/api/v1/stream
/api/v2/stream
```

❌ **Bad**:
```
/api/v1.2.3/stream  # Too specific
```

### 2. Deprecate Before Sunset

✅ **Good**:
```
1. Announce deprecation (3 months notice)
2. Add deprecation headers
3. Sunset after deprecation period
```

❌ **Bad**:
```
Sunset immediately without warning
```

### 3. Provide Migration Guide

✅ **Good**:
```
Documentation with:
- What changed
- How to migrate
- Code examples
- Timeline
```

### 4. Limit Active Versions

✅ **Good**:
```
Maximum 2 active versions:
- V1: Deprecated
- V2: Active
```

❌ **Bad**:
```
Supporting V1, V2, V3, V4 simultaneously
```

## Monitoring

### Metrics to Track

1. **Version Usage**: Requests per version
   - Track adoption of new versions
   - Identify clients still on old versions

2. **Deprecation Warnings**: Count of deprecated version usage
   - Alert when usage is still high near sunset

3. **Migration Progress**: Percentage of clients on latest version
   - Target: >90% before sunset

## References

- **API Versioning Best Practices**: https://restfulapi.net/versioning/
- **Semantic Versioning**: https://semver.org/
- **Implementation**: `src/application/app.py:239-244`

## Success Criteria

✅ **Achieved** if:
1. All endpoints prefixed with `/api/v1`
2. Version visible in URL
3. Deprecation process defined
4. Migration guide available
5. Multiple versions can coexist

## Conclusion

URL path prefix versioning with `/api/v{N}` provides **professional, flexible API versioning**. By including the major version in the URL path, we achieve:

- **Backward compatibility** (old clients keep working)
- **Gradual migration** (clients upgrade at their own pace)
- **Clear deprecation** (sunset process is transparent)
- **Professional URLs** (industry-standard structure)
- **Flexibility** (can introduce breaking changes safely)

This strategy is **essential for long-term API evolution** while maintaining client trust and minimizing disruption.
