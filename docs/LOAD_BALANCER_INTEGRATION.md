# Load Balancer Integration - Complete Educational Guide

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Integration Points](#integration-points)
3. [Request Flow Walkthrough](#request-flow-walkthrough)
4. [Configuration Files](#configuration-files)
5. [Code Annotations](#code-annotations)
6. [Testing Load Distribution](#testing-load-distribution)
7. [Common Pitfalls](#common-pitfalls)

---

## Architecture Overview

### The Complete System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER's BROWSER                              │
│                   http://localhost:3001                             │
└────────────────────────┬────────────────────────────────────────────┘
                         │
                         │ (1) HTTP Request
                         │     POST /api/v1/stream
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│              PERFORMANCE DASHBOARD (React/Vite)                     │
│                   Frontend Application                              │
│                                                                     │
│  File: performance_dashboard/src/api.js                            │
│  const API_BASE_URL = 'https://localhost/api/v1'  ← CRITICAL!     │
│                                     ↑                               │
│                                     └─ This URL determines          │
│                                        if load balancer is used     │
└────────────────────────┬────────────────────────────────────────────┘
                         │
                         │ (2) HTTPS Request
                         │     https://localhost/api/v1/stream
                         │     ↑
                         │     └─ Notice: Port 443 (implicit)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    NGINX LOAD BALANCER                              │
│                   (Docker Container)                                │
│                                                                     │
│  Listens on: Port 80 (HTTP) and 443 (HTTPS)                       │
│  Config: infrastructure/nginx/nginx.conf                           │
│                                                                     │
│  upstream sse_backend {                                            │
│      least_conn;  ← Uses "least connections" algorithm            │
│      server app-1:8000;  ← Docker service name                    │
│      server app-2:8000;                                            │
│      server app-3:8000;                                            │
│  }                                                                 │
└────────┬──────────────┬──────────────┬─────────────────────────────┘
         │              │              │
         │ (3a) Proxy   │ (3b) Proxy   │ (3c) Proxy
         │ 33% traffic  │ 33% traffic  │ 34% traffic
         ▼              ▼              ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  FastAPI     │  │  FastAPI     │  │  FastAPI     │
│  Instance 1  │  │  Instance 2  │  │  Instance 3  │
│  (app-1)     │  │  (app-2)     │  │  (app-3)     │
│              │  │              │  │              │
│  Port: 8000  │  │  Port: 8000  │  │  Port: 8000  │
│  (internal)  │  │  (internal)  │  │  (internal)  │
│              │  │              │  │              │
│  Connection  │  │  Connection  │  │  Connection  │
│  Pool: 3/usr │  │  Pool: 3/usr │  │  Pool: 3/usr │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ REDIS CLUSTER │
                 │  (Shared)     │
                 └───────────────┘
```

---

## Integration Points

### 1. **Frontend API Configuration** (UI → Load Balancer)

**File**: `performance_dashboard/src/api.js`

**Purpose**: Configures where the React frontend sends API requests

**Critical Line**:
```javascript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://localhost/api/v1';
                                                            ^^^^^^^^^^^^^^^^^^^^^^
                                                            THIS IS THE KEY!
```

**Why This Matters**:
- ✅ `https://localhost/api/v1` → Routes through NGINX (port 443) → Load balanced
- ❌ `http://localhost:8000/api/v1` → Bypasses NGINX → Direct to single instance

**Visual Representation**:
```
┌─────────────────────────────────────────────────────────────┐
│ Frontend Request (from browser)                             │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
    CORRECT URL                    WRONG URL
 https://localhost                http://localhost:8000
         │                               │
         ▼                               ▼
    ✅ NGINX                        ❌ Bypasses NGINX
    Port 443                        Direct Connection
         │                               │
         ▼                               ▼
  Load Balanced                   Single Instance
  (3 instances)                   (No distribution)
```

---

### 2. **NGINX Configuration** (Load Balancer → Backend)

**File**: `infrastructure/nginx/nginx.conf`

**Key Sections**:

#### Section A: Upstream Definition (Lines 296-402)
```nginx
upstream sse_backend {
    # LOAD BALANCING ALGORITHM
    # ------------------------
    # least_conn: Send request to server with fewest active connections
    # Perfect for long-lived SSE streaming connections
    least_conn;
    
    # BACKEND SERVERS
    # ---------------
    # Docker service names resolve to container IPs automatically
    server app-1:8000 max_fails=3 fail_timeout=30s;
    server app-2:8000 max_fails=3 fail_timeout=30s;
    server app-3:8000 max_fails=3 fail_timeout=30s;
    
    # CONNECTION POOLING
    # ------------------
    # Maintain 32 persistent connections to backend
    # Reduces latency by reusing TCP connections
    keepalive 32;
}
```

**How NGINX Knows Which Backend to Use**:
1. Client connects to NGINX
2. NGINX checks current connections to each backend
3. Selects backend with **fewest active connections**
4. Proxies request to selected backend
5. Maintains connection state for load balancing

#### Section B: HTTP to HTTPS Redirect (Lines 422-432)
```nginx
server {
    listen 80;  # HTTP port
    server_name _;
    
    # FORCE HTTPS
    # All HTTP requests automatically redirected to HTTPS
    return 301 https://$host$request_uri;
}
```

**Why This Matters**:
- Ensures all traffic uses HTTPS (encrypted)
- Security best practice
- Prevents accidental unencrypted connections

#### Section C: HTTPS Server Block (Lines 438-780)
```nginx
server {
    listen 443 ssl;  # HTTPS port
    http2 on;        # Enable HTTP/2 for better performance
    
    # SSL CERTIFICATES
    ssl_certificate /etc/nginx/ssl/localhost.crt;
    ssl_certificate_key /etc/nginx/ssl/localhost.key;
    
    # PROXY ALL REQUESTS TO BACKEND
    location / {
        # THIS IS WHERE LOAD BALANCING HAPPENS!
        proxy_pass http://sse_backend;  ← References upstream block
        
        # Preserve client information
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $host;
        
        # Enable streaming (critical for SSE)
        proxy_buffering off;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        
        # Long timeouts for streaming connections
        proxy_read_timeout 300s;  # 5 minutes
    }
}
```

**Request Flow Through NGINX**:
```
1. Client → NGINX:443 (HTTPS)
2. NGINX decrypts SSL
3. NGINX selects backend (least_conn algorithm)
4. NGINX → app-X:8000 (HTTP, internal network)
5. Backend processes request
6. NGINX ← app-X (streaming response)
7. Client ← NGINX (encrypted streaming response)
```

---

### 3. **Docker Compose Configuration** (Infrastructure → Services)

**File**: `docker-compose.yml`

**Key Sections**:

#### Section A: NGINX Service (Lines 53-93)
```yaml
nginx:
  image: nginx:1.25-alpine
  container_name: sse-nginx
  
  # PORT MAPPING - CRITICAL!
  # -------------------------
  # Maps host ports to container ports
  # 80:80   → HTTP  (redirects to HTTPS)
  # 443:443 → HTTPS (main entry point)
  ports:
    - "80:80"     # Host port 80 → Container port 80
    - "443:443"   # Host port 443 → Container port 443
  
  # VOLUME MOUNTS
  # -------------
  # Mount configuration files into container
  volumes:
    - ./infrastructure/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./infrastructure/nginx/ssl:/etc/nginx/ssl:ro
  
  # DEPENDENCIES
  # ------------
  # NGINX waits for at least one backend to be healthy
  depends_on:
    app-1:
      condition: service_healthy
  
  networks:
    - sse-network  # Same network as backend services
```

**Why Port Mapping Matters**:
```
                Outside World         Inside Container
                (Your Machine)        (Docker Network)
                ──────────────        ────────────────
Browser →       localhost:443    →    container:443  → NGINX
                      ↑                      ↑
                      └──────────────────────┘
                         Docker Port Mapping
```

#### Section B: Backend Services (Lines 96-230)
```yaml
# INSTANCE 1
app-1:
  build: .
  container_name: sse-app-1
  # NO PORT MAPPING! Not exposed to host
  # Only accessible via Docker network
  networks:
    - sse-network  # Same network as NGINX
  
# INSTANCE 2
app-2:
  build: .
  container_name: sse-app-2
  networks:
    - sse-network
  
# INSTANCE 3
app-3:
  build: .
  container_name: sse-app-3
  networks:
    - sse-network
```

**Critical Observation**:
- Backend services have **NO port mapping** to host
- Only accessible via Docker internal network
- NGINX can reach them via service names (`app-1`, `app-2`, `app-3`)
- Host machine **CANNOT** directly access them

**Network Isolation**:
```
┌─────────────────────────────────────────────────┐
│ Host Machine (Your Computer)                    │
│                                                  │
│  Browser can access:                            │
│  ✅ localhost:443 (NGINX)                       │
│  ❌ app-1:8000 (not exposed)                    │
│  ❌ app-2:8000 (not exposed)                    │
│  ❌ app-3:8000 (not exposed)                    │
└─────────────────────────────────────────────────┘
                    │
                    │ Docker Port Mapping (443:443)
                    ▼
┌─────────────────────────────────────────────────┐
│ Docker Network (sse-network)                    │
│                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │  nginx   │   │  app-1   │   │  app-2   │    │
│  │  :443    │   │  :8000   │   │  :8000   │    │
│  └────┬─────┘   └────▲─────┘   └────▲─────┘    │
│       │              │              │           │
│       └──────────────┴──────────────┘           │
│         Internal communication only             │
└─────────────────────────────────────────────────┘
```

---

## Request Flow Walkthrough

### Example: Load Tester Sends 10 Concurrent Requests

**Step 1: Frontend Initiates Request**

**File**: `performance_dashboard/src/components/LoadTester.jsx`

```javascript
// Line 77
await fetchEventSource(`${API_BASE_URL}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        query: "Write a short poem about performance testing.",
        model: "gpt-3.5-turbo",
        provider: "fake",
        stream: true
    }),
    // ... SSE event handlers
});
```

**What Happens**:
```
API_BASE_URL = 'https://localhost/api/v1'
Full URL = 'https://localhost/api/v1/stream'
           └─────────┬─────────┘
                     │
              Goes to NGINX port 443
```

---

**Step 2: NGINX Receives Requests**

**NGINX Log**:
```nginx
127.0.0.1 - - [09/Dec/2025:17:14:05 +0000] "POST /api/v1/stream HTTP/1.1" ...
```

**Internal Processing**:
```nginx
# NGINX evaluates upstream block
upstream sse_backend {
    least_conn;
    server app-1:8000;  # Current connections: 0
    server app-2:8000;  # Current connections: 0
    server app-3:8000;  # Current connections: 0
}

# First 3 requests:
Request 1 → app-1 (connections: 0 → 1)
Request 2 → app-2 (connections: 0 → 1)
Request 3 → app-3 (connections: 0 → 1)

# Next 3 requests (all backends have 1 connection):
Request 4 → app-1 (connections: 1 → 2)
Request 5 → app-2 (connections: 1 → 2)
Request 6 → app-3 (connections: 1 → 2)

# Next 3 requests:
Request 7 → app-1 (connections: 2 → 3)
Request 8 → app-2 (connections: 2 → 3)
Request 9 → app-3 (connections: 2 → 3)

# 10th request (all backends have 3 connections):
Request 10 → app-1 (connections: 3 → attempts 4)
```

---

**Step 3: Backend Processes Requests**

**Backend Log** (app-1):
```json
{"stage": "CP.1", "user_id": "192.168.1.16", "event": "Attempting to acquire connection"}
{"stage": "CP.1.4", "user_connections": 1, "event": "Connection acquired"}
{"stage": "5.2", "event": "Starting stream"}
... (streaming response)
```

**Connection Pool Check**:
```python
# src/core/resilience/connection_pool_manager.py

async def acquire_connection(self, user_id: str, thread_id: str):
    # Check global limit
    if total_count >= 10000:
        raise ConnectionPoolExhaustedError()  # 503
    
    # Check per-user limit PER INSTANCE
    if user_count >= 3:  # ← This is per instance!
        raise UserConnectionLimitError()  # 429
    
    # Reserve connection
    await self._increment_counts(user_id, thread_id)
```

---

**Step 4: Distribution Summary**

With **load balancing**:
```
User sends 10 requests
├─ app-1 accepts 3 ✅ (200 OK - streaming)
├─ app-2 accepts 3 ✅ (200 OK - streaming)
├─ app-3 accepts 3 ✅ (200 OK - streaming)
└─ app-1 rejects 1 ❌ (429 - user pool exhausted)

Result: 9 successful, 1 rejected
Total capacity: 3 × 3 = 9 connections per user
```

Without **load balancing** (direct to single instance):
```
User sends 10 requests
└─ Local dev accepts 3 ✅ (200 OK - streaming)
   └─ Rejects 7 ❌ (429 - user pool exhausted)

Result: 3 successful, 7 rejected
Total capacity: 3 connections per user
```

---

## Configuration Files Summary

### File Structure
```
SSE/
├── performance_dashboard/
│   └── src/
│       └── api.js                     ← Frontend API URL (CRITICAL!)
│
├── infrastructure/
│   ├── nginx/
│   │   ├── nginx.conf                 ← Load balancer config
│   │   └── ssl/
│   │       ├── localhost.crt          ← SSL certificate
│   │       └── localhost.key          ← SSL private key
│   │
│   └── manage.py                      ← Infrastructure startup script
│
├── docker-compose.yml                 ← Service orchestration
│
└── src/
    └── core/
        └── resilience/
            └── connection_pool_manager.py  ← Per-instance limits
```

### Configuration Matrix

| File | Purpose | Load Balancing Impact |
|------|---------|----------------------|
| **`api.js`** | Frontend API URL | ⭐⭐⭐⭐⭐ **CRITICAL** - Determines if NGINX is used |
| **`nginx.conf`** | Load balancer rules | ⭐⭐⭐⭐⭐ Defines distribution algorithm |
| **`docker-compose.yml`** | Service deployment | ⭐⭐⭐⭐ Port mappings and networking |
| **`connection_pool_manager.py`** | Per-instance limits | ⭐⭐⭐ Enforces limits on each backend |

---

## Code Annotations

### Frontend: `performance_dashboard/src/api.js`

```javascript
// ===========================================================================
// LOAD BALANCER INTEGRATION POINT
// ===========================================================================
// This URL determines the entire request routing:
//
// Option 1: https://localhost/api/v1 (RECOMMENDED)
// ───────────────────────────────────────────────
// Flow: Browser → NGINX:443 → app-1/app-2/app-3:8000
// Result: Load balanced across 3 instances
// Capacity: 9 concurrent connections per user (3 × 3)
//
// Option 2: http://localhost:8000/api/v1 (DEVELOPMENT ONLY)
// ──────────────────────────────────────────────────────────
// Flow: Browser → Local FastAPI:8000
// Result: Direct connection, bypasses NGINX entirely
// Capacity: 3 concurrent connections per user
//
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://localhost/api/v1';
```

### NGINX: `infrastructure/nginx/nginx.conf`

```nginx
# ===========================================================================
# UPSTREAM BACKEND POOL
# ===========================================================================
# Defines the pool of backend servers that NGINX can forward requests to.
# NGINX automatically distributes traffic across these servers using the
# configured load balancing algorithm.

upstream sse_backend {
    # LOAD BALANCING ALGORITHM: least_conn
    # ────────────────────────────────────
    # Routes new requests to the server with the fewest active connections.
    # Perfect for long-lived SSE streaming connections because:
    # - Prevents overloading any single instance
    # - Maintains even distribution as connections come and go
    # - Better than round-robin for varying connection durations
    least_conn;
    
    # BACKEND SERVER POOL
    # ───────────────────
    # Docker service names (app-1, app-2, app-3) resolve automatically
    # via Docker's internal DNS to container IP addresses
    server app-1:8000 max_fails=3 fail_timeout=30s;
    server app-2:8000 max_fails=3 fail_timeout=30s;
    server app-3:8000 max_fails=3 fail_timeout=30s;
}

# ===========================================================================
# HTTPS SERVER - MAIN ENTRY POINT
# ===========================================================================
server {
    listen 443 ssl;
    
    location / {
        # LOAD BALANCING HAPPENS HERE!
        # ────────────────────────────
        # proxy_pass forwards requests to the upstream block defined above.
        # NGINX automatically selects which backend server to use based on
        # the least_conn algorithm.
        proxy_pass http://sse_backend;
        
        # Preserve client information for backend
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Backend: `src/core/resilience/connection_pool_manager.py`

```python
class ConnectionPoolManager:
    """
    IMPORTANT: This connection pool is PER INSTANCE!
    
    With load balancing:
    ────────────────────
    - Each of 3 instances has separate pool
    - Each pool allows 3 connections per user
    - Total capacity: 3 × 3 = 9 connections per user
    
    Without load balancing:
    ───────────────────────
    - Single instance has one pool
    - Pool allows 3 connections per user
    - Total capacity: 3 connections per user
    """
    
    def __init__(self, max_per_user: int = 3):
        self.max_per_user = max_per_user  # Per user, per instance
```

---

## Testing Load Distribution

### Manual Test

**Step 1: Verify NGINX is Running**
```bash
docker-compose ps nginx
```

**Expected Output**:
```
NAME        IMAGE              STATUS                   PORTS
sse-nginx   nginx:1.25-alpine  Up X minutes (healthy)   0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

**Step 2: Send Test Request Through NGINX**
```bash
curl -k https://localhost/api/v1/health
```

**Expected**:
```json
{"status": "healthy", "redis": "connected", "timestamp": "..."}
```

**Step 3: Monitor Backend Logs**
```bash
# Terminal 1: app-1 logs
docker logs sse-app-1 -f

# Terminal 2: app-2 logs
docker logs sse-app-2 -f

# Terminal 3: app-3 logs
docker logs sse-app-3 -f
```

**Step 4: Run Load Test**

From Performance Dashboard:
- Set concurrency: 10
- Set total requests: 30
- Click "Run Load Test"

**Expected Distribution**:
```
app-1 logs: ~10 requests (33%)
app-2 logs: ~10 requests (33%)
app-3 logs: ~10 requests (33%)
```

---

## Common Pitfalls

### ❌ Pitfall 1: Wrong API URL

**Symptom**:
```
All requests go to single instance
429 errors after only 3 concurrent connections
Load test capacity limited to 3
```

**Cause**:
```javascript
// WRONG: Bypasses NGINX
const API_BASE_URL = 'http://localhost:8000/api/v1';
```

**Fix**:
```javascript
// CORRECT: Routes through NGINX
const API_BASE_URL = 'https://localhost/api/v1';
```

---

### ❌ Pitfall 2: NGINX Not Running

**Symptom**:
```
ERR_CONNECTION_REFUSED when accessing https://localhost
```

**Diagnosis**:
```bash
docker-compose ps nginx
# Shows: nginx is not running or restarting
```

**Fix**:
```bash
# Check logs for errors
docker logs sse-nginx

# Common issue: Missing SSL certificates
# Solution: Certificates auto-generated by manage.py

# Restart infrastructure
python infrastructure/manage.py start
```

---

### ❌ Pitfall 3: Backend Not Reachable from NGINX

**Symptom**:
```
502 Bad Gateway from NGINX
NGINX logs show: upstream connect failed
```

**Diagnosis**:
```bash
# Check if backends are running
docker-compose ps app-1 app-2 app-3
```

**Fix**:
```bash
# Start all services
python infrastructure/manage.py start --all

# Verify backends are healthy
docker-compose ps
```

---

### ❌ Pitfall 4: SSL Certificate Issues

**Symptom**:
```
NGINX shows: cannot load certificate
Browser shows: ERR_SSL_PROTOCOL_ERROR
```

**Fix**:
```bash
# Certificates are auto-generated by manage.py
python infrastructure/manage.py start

# Verify certificates exist
ls infrastructure/nginx/ssl/
# Should show: localhost.crt, localhost.key
```

---

## Quick Reference

### ✅ Correct Setup Checklist

- [ ] NGINX running: `docker-compose ps nginx` shows healthy
- [ ] 3 backends running: `docker-compose ps app-1 app-2 app-3`
- [ ] API URL uses HTTPS: `https://localhost/api/v1`
- [ ] SSL certificates exist: `ls infrastructure/nginx/ssl/`
- [ ] Performance dashboard accessible: `http://localhost:3001`

### 🚀 Quick Start Commands

```bash
# Full production setup
python infrastructure/manage.py start --all

# Verify load balancer
curl -k https://localhost/api/v1/health

# Monitor distribution
docker logs sse-app-1 -f &
docker logs sse-app-2 -f &
docker logs sse-app-3 -f &

# Run load test from dashboard
# http://localhost:3001
```

### 📊 Expected Results

**Single Instance (Wrong Setup)**:
- Capacity: 3 connections per user
- All requests to one instance
- 70% failure rate with 10 concurrent requests

**Load Balanced (Correct Setup)**:
- Capacity: 9 connections per user (3 × 3)
- Requests distributed evenly
- 10% failure rate with 10 concurrent requests
- 3x better performance

---

**Created**: 2025-12-09  
**Last Updated**: 2025-12-09  
**Status**: ✅ Complete - Ready for Production
