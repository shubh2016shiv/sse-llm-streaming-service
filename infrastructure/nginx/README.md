# NGINX Load Balancer Infrastructure

**Enterprise-grade load balancing and reverse proxy for the SSE Streaming Application**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [How It Works](#how-it-works)
5. [Integration with Infrastructure](#integration-with-infrastructure)
6. [Configuration Deep Dive](#configuration-deep-dive)
7. [Load Balancing Strategies](#load-balancing-strategies)
8. [SSL/TLS Configuration](#ssltls-configuration)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This directory contains the NGINX load balancer configuration for the SSE application. NGINX acts as a reverse proxy, distributing incoming requests across multiple application instances while providing SSL termination, health checking, and performance optimizations specifically tuned for Server-Sent Events (SSE) streaming.

### Key Features

- **Load Balancing**: Distributes traffic across 3 application instances using least-connections algorithm
- **SSL/TLS Termination**: Handles HTTPS encryption at the edge
- **Health Checking**: Automatically removes unhealthy instances from rotation
- **SSE Optimization**: Disabled buffering for real-time streaming
- **High Availability**: Zero downtime deployments and automatic failover
- **Performance**: Optimized for low latency and high throughput

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph "External"
        CLIENT[Client Browser<br/>HTTPS Request]
    end
    
    subgraph "NGINX Load Balancer :80/:443"
        LB[NGINX<br/>Reverse Proxy]
        SSL[SSL Termination]
        HEALTH[Health Checker]
    end
    
    subgraph "Backend Pool"
        APP1[App Instance 1<br/>:8000]
        APP2[App Instance 2<br/>:8000]
        APP3[App Instance 3<br/>:8000]
    end
    
    CLIENT -->|HTTPS| SSL
    SSL --> LB
    LB -->|Least Connections| APP1
    LB -->|Least Connections| APP2
    LB -->|Least Connections| APP3
    
    HEALTH -.->|Health Check| APP1
    HEALTH -.->|Health Check| APP2
    HEALTH -.->|Health Check| APP3
    
    style LB fill:#f9f,stroke:#333,stroke-width:2px
    style SSL fill:#9f9,stroke:#333,stroke-width:2px
    style HEALTH fill:#ff9,stroke:#333,stroke-width:2px
```

### Request Flow

```mermaid
sequenceDiagram
    participant Client
    participant NGINX
    participant App1 as App Instance 1
    participant App2 as App Instance 2
    participant App3 as App Instance 3
    
    Note over NGINX: Least Connections Algorithm<br/>Tracks active connections
    
    Client->>NGINX: HTTPS Request
    Note over NGINX: SSL Termination
    
    NGINX->>NGINX: Check active connections:<br/>App1: 5, App2: 3, App3: 4
    
    Note over NGINX: Select App2<br/>(fewest connections)
    
    NGINX->>App2: HTTP Request (proxied)
    App2-->>NGINX: SSE Stream (chunked)
    
    Note over NGINX: Buffering OFF<br/>Stream immediately
    
    NGINX-->>Client: HTTPS Stream
    
    Note over NGINX: Connection remains open<br/>for duration of stream
```

---

## Directory Structure

```
infrastructure/nginx/
├── README.md                          # This file
├── nginx.conf                         # Main NGINX configuration
├── conf.d/                            # Additional configurations (if needed)
├── ssl/                               # SSL certificates
│   ├── localhost.crt                 # Self-signed certificate (dev)
│   ├── localhost.key                 # Private key (dev)
│   ├── generate-certs.sh             # Certificate generation script
│   └── README.md                     # SSL documentation
├── NGINX_LOAD_BALANCING.md           # Detailed load balancing guide
└── VERIFICATION_REPORT.md            # Load balancer verification results
```

### File Purposes

| File | Purpose | When It's Used |
|------|---------|----------------|
| `nginx.conf` | Main configuration defining load balancing, SSL, and proxy settings | Read by NGINX on startup |
| `ssl/localhost.crt` | SSL certificate for HTTPS | Used for every HTTPS connection |
| `ssl/localhost.key` | Private key for SSL certificate | Used for every HTTPS connection |
| `conf.d/*.conf` | Additional configuration files (optional) | Included by main nginx.conf |

---

## How It Works

### 1. Infrastructure Startup Sequence

When you run `python infrastructure/manage.py start`, here's the NGINX lifecycle:

```mermaid
sequenceDiagram
    participant User
    participant ManagePy as manage.py
    participant Docker as Docker Compose
    participant NGINX
    participant Apps as App Instances
    
    User->>ManagePy: python manage.py start
    
    Note over ManagePy: Pre-flight checks
    
    ManagePy->>Docker: docker compose up -d
    
    Note over Docker: Start services in order
    
    Docker->>Apps: Start app-1, app-2, app-3
    Note over Apps: Expose :8000<br/>Wait for health
    
    Docker->>NGINX: Start NGINX
    
    Note over NGINX: 1. Load nginx.conf
    
    NGINX->>NGINX: Parse upstream block<br/>(app-1, app-2, app-3)
    
    NGINX->>NGINX: Load SSL certificates
    
    NGINX->>NGINX: Start worker processes<br/>(1 per CPU core)
    
    Note over NGINX: 2. Begin health checks
    
    loop Every request
        NGINX->>Apps: Passive health check<br/>(max_fails=3)
    end
    
    NGINX->>NGINX: Listen on :80 and :443
    
    Note over NGINX: 3. Ready to accept traffic
    
    ManagePy->>NGINX: Check health endpoint
    NGINX-->>ManagePy: 200 OK
    ManagePy-->>User: ✅ Infrastructure ready
```

### 2. Docker Compose Integration

The `docker-compose.yml` file defines how NGINX runs and connects to backend services:

```yaml
nginx:
  image: nginx:1.25-alpine
  ports:
    - "80:80"      # HTTP (redirects to HTTPS)
    - "443:443"    # HTTPS (main entry point)
  
  volumes:
    # Mount NGINX configuration
    - ./infrastructure/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    
    # Mount SSL certificates
    - ./infrastructure/nginx/ssl:/etc/nginx/ssl:ro
  
  depends_on:
    app-1:
      condition: service_healthy
    app-2:
      condition: service_healthy
    app-3:
      condition: service_healthy
  
  healthcheck:
    test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", 
           "http://localhost/nginx-health"]
    interval: 10s
    timeout: 5s
    retries: 3
```

**Critical Design Decisions**:

| Decision | Rationale |
|----------|-----------|
| `depends_on` with `service_healthy` | NGINX only starts after all app instances are healthy |
| Read-only mounts (`:ro`) | Prevents accidental configuration changes |
| Alpine image | Smaller image size, faster startup |
| Health check endpoint | Enables orchestration tools to monitor NGINX health |

### 3. Load Balancing Algorithm

NGINX uses the **Least Connections** algorithm for SSE streaming:

```mermaid
flowchart TD
    Start[New Request Arrives] --> Count[Count active connections<br/>for each backend]
    
    Count --> App1{App 1:<br/>5 connections}
    Count --> App2{App 2:<br/>3 connections}
    Count --> App3{App 3:<br/>7 connections}
    
    App1 --> Select
    App2 --> Select[Select backend with<br/>FEWEST connections]
    App3 --> Select
    
    Select --> Route[Route to App 2]
    Route --> Increment[Increment App 2<br/>connection count]
    Increment --> Proxy[Proxy request]
    
    Proxy --> Stream{Is SSE stream?}
    Stream -->|Yes| LongLived[Keep connection open<br/>for stream duration]
    Stream -->|No| ShortLived[Close after response]
    
    LongLived --> Decrement[Decrement count<br/>when stream ends]
    ShortLived --> Decrement
    
    style Select fill:#9f9,stroke:#333,stroke-width:2px
    style Route fill:#f9f,stroke:#333,stroke-width:2px
```

**Why Least Connections for SSE?**

| Algorithm | Best For | Why NOT for SSE? |
|-----------|----------|------------------|
| Round Robin | Short-lived requests of equal duration | Doesn't account for long-lived SSE connections |
| IP Hash | Session affinity (sticky sessions) | Not needed; app is stateless (uses Redis) |
| **Least Connections** | **Long-lived connections** | **✅ Perfect for SSE streams** |

---

## Integration with Infrastructure

### manage.py Orchestration

The `infrastructure/manage.py` script manages NGINX as a core service:

#### Service Definitions

```python
# From manage.py
CORE_SERVICES = [
    "redis-master",
    "zookeeper",
    "kafka",
    "nginx",        # ← Load balancer (this component)
    "prometheus",
    "grafana"
]
```

NGINX is a **core service**, meaning:
- Starts automatically with infrastructure
- Must be healthy before system is considered ready
- Monitored for health continuously

#### Dependency Chain

```mermaid
graph LR
    subgraph "Service Dependencies"
        APP1[app-1]
        APP2[app-2]
        APP3[app-3]
        NGINX[nginx]
    end
    
    APP1 -->|depends_on| NGINX
    APP2 -->|depends_on| NGINX
    APP3 -->|depends_on| NGINX
    
    style NGINX fill:#f9f,stroke:#333,stroke-width:3px
```

NGINX **depends on** all app instances being healthy. This ensures:
1. No requests are routed to unhealthy backends
2. Load balancer starts only when backends are ready
3. Clean startup sequence

### Health Monitoring

#### NGINX Health Check

```yaml
# From docker-compose.yml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", 
         "http://localhost/nginx-health"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 30s
```

**Health Check Endpoint** (`/nginx-health`):
```nginx
location /nginx-health {
    access_log off;  # Don't log health checks
    return 200 "NGINX is healthy\n";
    add_header Content-Type text/plain;
}
```

#### Backend Health Checks

NGINX performs **passive health checks** on backend instances:

```nginx
upstream sse_backend {
    least_conn;
    
    server app-1:8000 max_fails=3 fail_timeout=30s;
    server app-2:8000 max_fails=3 fail_timeout=30s;
    server app-3:8000 max_fails=3 fail_timeout=30s;
}
```

**Health Check Logic**:

```mermaid
stateDiagram-v2
    [*] --> Healthy: Backend starts
    
    Healthy --> Checking: Request sent
    Checking --> Healthy: Success (200-399)
    Checking --> FailCount: Failure (500-599)
    
    FailCount --> Healthy: Success (reset counter)
    FailCount --> FailCount: Failure (increment)
    FailCount --> Unhealthy: 3 consecutive failures
    
    Unhealthy --> WaitTimeout: Wait 30 seconds
    WaitTimeout --> Checking: Retry request
    
    note right of Unhealthy
        Backend removed from rotation
        No traffic sent
    end note
```

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `max_fails` | 3 | Mark unhealthy after 3 consecutive failures |
| `fail_timeout` | 30s | Wait 30s before retrying unhealthy backend |

---

## Configuration Deep Dive

### Worker Process Configuration

```nginx
user nginx;
worker_processes auto;  # 1 worker per CPU core
```

**Why `auto`?**

```mermaid
graph LR
    CPU1[CPU Core 1] --> W1[Worker 1]
    CPU2[CPU Core 2] --> W2[Worker 2]
    CPU3[CPU Core 3] --> W3[Worker 3]
    CPU4[CPU Core 4] --> W4[Worker 4]
    
    W1 --> Conn1[1000+ connections]
    W2 --> Conn2[1000+ connections]
    W3 --> Conn3[1000+ connections]
    W4 --> Conn4[1000+ connections]
    
    style W1 fill:#9cf
    style W2 fill:#9cf
    style W3 fill:#9cf
    style W4 fill:#9cf
```

- Maximizes CPU utilization
- Each worker handles connections independently
- No inter-worker communication overhead
- Scales automatically with hardware

### Event Processing

```nginx
events {
    worker_connections 1024;  # Max connections per worker
    use epoll;                # Linux-optimized event mechanism
    multi_accept on;          # Accept multiple connections at once
}
```

**Connection Capacity**:
```
Total Capacity = worker_processes × worker_connections
Example: 4 cores × 1024 = 4,096 concurrent connections
```

### Upstream Configuration

```nginx
upstream sse_backend {
    least_conn;  # Load balancing algorithm
    
    server app-1:8000 max_fails=3 fail_timeout=30s;
    server app-2:8000 max_fails=3 fail_timeout=30s;
    server app-3:8000 max_fails=3 fail_timeout=30s;
    
    keepalive 32;  # Connection pool to backends
}
```

**Keepalive Connections**:

```mermaid
sequenceDiagram
    participant NGINX
    participant Pool as Connection Pool
    participant App as App Instance
    
    Note over Pool: Pool size: 32 connections
    
    NGINX->>Pool: Need connection
    Pool->>Pool: Check for idle connection
    
    alt Idle connection available
        Pool-->>NGINX: Reuse existing connection
    else No idle connection
        Pool->>App: Establish new connection
        App-->>Pool: Connection established
        Pool-->>NGINX: New connection
    end
    
    NGINX->>App: Send request
    App-->>NGINX: Response
    
    NGINX->>Pool: Return connection to pool
    
    Note over Pool: Connection stays open<br/>for next request
```

**Benefits**:
- Reduces latency (no TCP handshake overhead)
- Reduces backend load (fewer new connections)
- Improves throughput

### Proxy Configuration for SSE

**Critical Settings for Streaming**:

```nginx
location / {
    proxy_pass http://sse_backend;
    
    # Disable buffering (CRITICAL for SSE)
    proxy_buffering off;
    proxy_request_buffering off;
    
    # Long timeout for streams
    proxy_read_timeout 300s;  # 5 minutes
    
    # HTTP/1.1 for keepalive
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    
    # Prevent caching
    proxy_set_header Cache-Control "no-cache, no-store, must-revalidate";
    proxy_set_header X-Accel-Buffering no;
}
```

**Why Disable Buffering?**

```mermaid
graph TB
    subgraph "With Buffering (BAD for SSE)"
        App1[App generates chunk] --> Buffer[NGINX buffers]
        Buffer --> Wait[Wait for more chunks]
        Wait --> Full[Buffer full or timeout]
        Full --> Send1[Send to client]
    end
    
    subgraph "Without Buffering (GOOD for SSE)"
        App2[App generates chunk] --> Immediate[NGINX sends immediately]
        Immediate --> Client[Client receives]
    end
    
    style Buffer fill:#f99,stroke:#333,stroke-width:2px
    style Immediate fill:#9f9,stroke:#333,stroke-width:2px
```

---

## Load Balancing Strategies

### Comparison of Algorithms

| Algorithm | How It Works | Best For | SSE Suitability |
|-----------|--------------|----------|-----------------|
| **Round Robin** | Cycles through backends in order | Equal-capacity servers, short requests | ❌ Poor - doesn't account for long connections |
| **Least Connections** | Routes to backend with fewest active connections | Long-lived connections, varying request duration | ✅ **Excellent** - perfect for SSE |
| **IP Hash** | Same client IP always goes to same backend | Stateful apps requiring session affinity | ⚠️ Not needed - app is stateless |
| **Least Time** (Plus only) | Routes to fastest backend | Servers with varying performance | ✅ Good, but requires NGINX Plus |

### Least Connections in Action

**Scenario**: 3 app instances, 10 concurrent SSE streams

```mermaid
gantt
    title Load Distribution Over Time
    dateFormat  HH:mm:ss
    axisFormat %H:%M:%S
    
    section App 1
    Stream 1 :a1, 00:00:00, 60s
    Stream 4 :a2, 00:00:03, 45s
    Stream 7 :a3, 00:00:06, 30s
    
    section App 2
    Stream 2 :b1, 00:00:01, 50s
    Stream 5 :b2, 00:00:04, 40s
    Stream 8 :b3, 00:00:07, 35s
    
    section App 3
    Stream 3 :c1, 00:00:02, 55s
    Stream 6 :c2, 00:00:05, 42s
    Stream 9 :c3, 00:00:08, 38s
    Stream 10 :c4, 00:00:09, 25s
```

**Result**: Balanced distribution based on active connections, not just request count.

---

## SSL/TLS Configuration

### Certificate Management

**Development (Self-Signed)**:
```bash
# Generate self-signed certificate
cd infrastructure/nginx/ssl
./generate-certs.sh
```

**Production (Let's Encrypt)**:
```bash
# Use Certbot for free SSL certificates
certbot certonly --webroot -w /var/www/html -d yourdomain.com
```

### SSL Configuration

```nginx
server {
    listen 443 ssl;
    http2 on;
    
    ssl_certificate /etc/nginx/ssl/localhost.crt;
    ssl_certificate_key /etc/nginx/ssl/localhost.key;
    
    # Modern SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
}
```

### HTTP to HTTPS Redirect

```nginx
server {
    listen 80;
    server_name _;
    
    # Redirect all HTTP to HTTPS
    return 301 https://$host$request_uri;
}
```

**Flow**:

```mermaid
sequenceDiagram
    participant Client
    participant NGINX80 as NGINX :80
    participant NGINX443 as NGINX :443
    participant App
    
    Client->>NGINX80: HTTP GET /stream
    NGINX80-->>Client: 301 Redirect<br/>Location: https://...
    
    Client->>NGINX443: HTTPS GET /stream
    Note over NGINX443: SSL Termination
    NGINX443->>App: HTTP GET /stream<br/>(internal, unencrypted)
    App-->>NGINX443: SSE Stream
    Note over NGINX443: Re-encrypt
    NGINX443-->>Client: HTTPS Stream
```

---

## Troubleshooting

### Common Issues

#### 1. 502 Bad Gateway

**Symptom**: NGINX returns 502 error

**Diagnosis**:
```mermaid
flowchart TD
    Start[502 Bad Gateway] --> CheckBackend{Are backends<br/>running?}
    
    CheckBackend -->|No| StartBackend[Start app instances:<br/>manage.py start --all]
    CheckBackend -->|Yes| CheckHealth{Are backends<br/>healthy?}
    
    CheckHealth -->|No| FixBackend[Check app logs:<br/>docker compose logs app-1]
    CheckHealth -->|Yes| CheckNetwork{Can NGINX<br/>reach backends?}
    
    CheckNetwork -->|No| CheckDNS[Check Docker network:<br/>docker network inspect]
    CheckNetwork -->|Yes| CheckTimeout{Request<br/>timing out?}
    
    CheckTimeout -->|Yes| IncreaseTimeout[Increase proxy_read_timeout]
    CheckTimeout -->|No| CheckLogs[Check NGINX error logs]
    
    style StartBackend fill:#f99
    style FixBackend fill:#f99
    style CheckDNS fill:#f99
```

**Solution**:
```bash
# Check backend health
docker compose ps

# Check NGINX can reach backends
docker compose exec nginx ping app-1

# Check NGINX error logs
docker compose logs nginx --tail=50
```

#### 2. Slow Response Times

**Symptom**: Requests taking longer than expected

**Diagnosis**:

| Check | Command | What to Look For |
|-------|---------|------------------|
| NGINX access logs | `docker compose logs nginx \| grep "rt="` | High `rt=` (request time) values |
| Backend response time | `docker compose logs nginx \| grep "urt="` | High `urt=` (upstream response time) |
| Connection time | `docker compose logs nginx \| grep "uct="` | High `uct=` (upstream connect time) |

**Solution**:
```nginx
# Increase keepalive connections
upstream sse_backend {
    keepalive 64;  # Increase from 32
}

# Increase worker connections
events {
    worker_connections 2048;  # Increase from 1024
}
```

#### 3. SSL Certificate Errors

**Symptom**: Browser shows "Your connection is not private"

**For Development**:
- Expected with self-signed certificates
- Click "Advanced" → "Proceed to localhost"

**For Production**:
```bash
# Verify certificate is valid
openssl x509 -in /path/to/cert.crt -text -noout

# Check certificate expiration
openssl x509 -in /path/to/cert.crt -noout -dates
```

### Monitoring Commands

```bash
# Check NGINX status
docker compose ps nginx

# View real-time access logs
docker compose logs nginx --follow

# Check NGINX configuration syntax
docker compose exec nginx nginx -t

# Reload NGINX configuration (zero downtime)
docker compose exec nginx nginx -s reload

# View NGINX metrics
curl http://localhost/nginx-status
```

---

## Performance Tuning

### Optimization Checklist

| Setting | Default | Tuned | Impact |
|---------|---------|-------|--------|
| `worker_processes` | 1 | `auto` | ✅ Utilizes all CPU cores |
| `worker_connections` | 512 | 1024 | ✅ Handles more concurrent connections |
| `keepalive` (upstream) | 0 | 32 | ✅ Reduces backend connection overhead |
| `proxy_buffering` | on | `off` | ✅ Enables real-time SSE streaming |
| `sendfile` | off | `on` | ✅ Optimizes static file serving |
| `tcp_nodelay` | off | `on` | ✅ Reduces latency for streaming |

### Load Testing

```bash
# Test load balancing distribution
for i in {1..100}; do
    curl -s https://localhost/stream | grep "instance" &
done

# Monitor connection distribution
watch -n 1 'docker compose exec nginx cat /var/log/nginx/access.log | grep upstream | tail -20'
```

---

## Quick Reference

### Access URLs

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Application (HTTP) | http://localhost | Redirects to HTTPS |
| Application (HTTPS) | https://localhost | Main entry point |
| NGINX Health | http://localhost/nginx-health | Health check endpoint |
| NGINX Status | http://localhost/nginx-status | Metrics endpoint |

### Common Commands

```bash
# Start infrastructure (including NGINX)
python infrastructure/manage.py start

# Restart just NGINX
python infrastructure/manage.py restart --services nginx

# Reload NGINX config (zero downtime)
docker compose exec nginx nginx -s reload

# Test NGINX configuration
docker compose exec nginx nginx -t

# View NGINX logs
docker compose logs nginx --tail=50 --follow

# Check backend distribution
docker compose logs nginx | grep upstream | tail -20
```

---

## Professional Standards

This NGINX setup demonstrates:

✅ **High Availability**: Automatic failover and health checking  
✅ **Load Balancing**: Intelligent traffic distribution  
✅ **SSL/TLS Security**: Encrypted communication  
✅ **Performance Optimization**: Tuned for low latency and high throughput  
✅ **SSE-Specific Configuration**: Disabled buffering for real-time streaming  
✅ **Observability**: Comprehensive logging and metrics  
✅ **Zero Downtime**: Configuration reloads without dropping connections  
✅ **Documentation**: Extensively commented configuration

---

## Further Reading

- [NGINX Official Documentation](https://nginx.org/en/docs/)
- [NGINX Load Balancing Guide](https://docs.nginx.com/nginx/admin-guide/load-balancer/http-load-balancer/)
- [NGINX SSL/TLS Configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [Server-Sent Events Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [NGINX Performance Tuning](https://www.nginx.com/blog/tuning-nginx/)
