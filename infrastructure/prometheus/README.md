# Prometheus Monitoring Infrastructure

**Time-series metrics collection and alerting for the SSE Streaming Application**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [How It Works](#how-it-works)
5. [Integration with Infrastructure](#integration-with-infrastructure)
6. [Scrape Configuration](#scrape-configuration)
7. [Metrics and Labels](#metrics-and-labels)
8. [Alerting Rules](#alerting-rules)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This directory contains the Prometheus monitoring configuration for the SSE application. Prometheus is a time-series database and monitoring system that scrapes metrics from application instances, stores them efficiently, and enables powerful querying and alerting capabilities.

### Key Features

- **Multi-Target Scraping**: Collects metrics from app instances, NGINX, and Redis
- **Time-Series Storage**: Efficient storage with configurable retention
- **PromQL**: Powerful query language for metric analysis
- **Alerting**: Proactive detection of issues via alert rules
- **Service Discovery**: Automatic detection of Docker services
- **High Availability**: Designed for reliability and uptime

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph "Prometheus Server :9090"
        PROM[Prometheus]
        TSDB[(Time-Series<br/>Database)]
        RULES[Alert Rules<br/>Engine]
    end
    
    subgraph "Scrape Targets"
        APP1[App Instance 1<br/>:8000/admin/metrics]
        APP2[App Instance 2<br/>:8000/admin/metrics]
        APP3[App Instance 3<br/>:8000/admin/metrics]
        NGINX[NGINX<br/>:80/nginx-status]
        REDIS[Redis Exporter<br/>:9121/metrics]
    end
    
    subgraph "Consumers"
        GRAF[Grafana<br/>Dashboards]
        ALERT[Alertmanager<br/>Notifications]
    end
    
    PROM -->|Scrape every 15s| APP1
    PROM -->|Scrape every 15s| APP2
    PROM -->|Scrape every 15s| APP3
    PROM -->|Scrape every 15s| NGINX
    PROM -->|Scrape every 15s| REDIS
    
    PROM --> TSDB
    PROM --> RULES
    
    GRAF -->|PromQL queries| PROM
    RULES -->|Fire alerts| ALERT
    
    style PROM fill:#f9f,stroke:#333,stroke-width:2px
    style TSDB fill:#9cf,stroke:#333,stroke-width:2px
    style RULES fill:#ff9,stroke:#333,stroke-width:2px
```

### Data Flow

```mermaid
sequenceDiagram
    participant App as App Instance
    participant Prom as Prometheus
    participant TSDB as Time-Series DB
    participant Graf as Grafana
    
    Note over App: Application exposes<br/>/admin/metrics endpoint
    
    loop Every 15 seconds
        Prom->>App: HTTP GET /admin/metrics
        App-->>Prom: Metrics (Prometheus format)
        
        Note over Prom: Parse metrics<br/>Apply labels
        
        Prom->>TSDB: Store time-series data
        Note over TSDB: Append to existing series<br/>Create new series if needed
    end
    
    Note over Prom: Evaluate alert rules<br/>every 15 seconds
    
    Graf->>Prom: PromQL: rate(requests_total[5m])
    Prom->>TSDB: Query time-series
    TSDB-->>Prom: Data points
    Prom-->>Graf: Aggregated results
```

---

## Directory Structure

```
infrastructure/prometheus/
├── README.md                          # This file
├── prometheus.yml                     # Main configuration
├── alerts/                            # Alert rule definitions
│   └── sse_alerts.yml                # SSE application alerts
└── docs/                              # Additional documentation
    └── PROMETHEUS_SETUP.md           # Setup guide
```

### File Purposes

| File | Purpose | When It's Used |
|------|---------|----------------|
| `prometheus.yml` | Main configuration: scrape targets, intervals, alert rules | Read by Prometheus on startup |
| `alerts/sse_alerts.yml` | Alert rule definitions (high error rate, latency, etc.) | Evaluated every 15 seconds |
| `docs/PROMETHEUS_SETUP.md` | Detailed setup and configuration guide | Reference documentation |

---

## How It Works

### 1. Infrastructure Startup Sequence

When you run `python infrastructure/manage.py start`, here's the Prometheus lifecycle:

```mermaid
sequenceDiagram
    participant User
    participant ManagePy as manage.py
    participant Docker as Docker Compose
    participant Prom as Prometheus
    participant Targets as Scrape Targets
    
    User->>ManagePy: python manage.py start
    
    Note over ManagePy: Pre-flight checks
    
    ManagePy->>Docker: docker compose up -d
    
    Note over Docker: Start services in order
    
    Docker->>Targets: Start app instances, NGINX, Redis
    Note over Targets: Expose metrics endpoints
    
    Docker->>Prom: Start Prometheus
    
    Note over Prom: 1. Load prometheus.yml
    
    Prom->>Prom: Parse global config<br/>(scrape_interval: 15s)
    
    Prom->>Prom: Load alert rules<br/>from alerts/*.yml
    
    Prom->>Prom: Parse scrape_configs<br/>(define targets)
    
    Note over Prom: 2. Initialize TSDB
    
    Prom->>Prom: Create/open time-series database<br/>at /prometheus
    
    Note over Prom: 3. Start scraping
    
    loop Every 15 seconds
        Prom->>Targets: Scrape all targets
        Targets-->>Prom: Metrics data
        Prom->>Prom: Store in TSDB
    end
    
    Note over Prom: 4. Start alert evaluation
    
    loop Every 15 seconds
        Prom->>Prom: Evaluate alert rules
    end
    
    Note over Prom: 5. Ready to serve queries
    
    ManagePy->>Prom: Check health endpoint
    Prom-->>ManagePy: 200 OK
    ManagePy-->>User: ✅ Infrastructure ready
```

### 2. Docker Compose Integration

The `docker-compose.yml` file defines how Prometheus runs:

```yaml
prometheus:
  image: prom/prometheus:v2.48.0
  ports:
    - "9090:9090"
  
  volumes:
    # Mount configuration
    - ./infrastructure/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    
    # Mount alert rules
    - ./infrastructure/prometheus/alerts:/etc/prometheus/alerts:ro
    
    # Persistent storage for time-series data
    - prometheus-data:/prometheus
  
  command:
    - '--config.file=/etc/prometheus/prometheus.yml'
    - '--storage.tsdb.path=/prometheus'
    - '--storage.tsdb.retention.time=30d'  # Keep 30 days of data
    - '--web.console.libraries=/usr/share/prometheus/console_libraries'
    - '--web.console.templates=/usr/share/prometheus/consoles'
  
  healthcheck:
    test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", 
           "http://localhost:9090/-/healthy"]
    interval: 10s
    timeout: 5s
    retries: 3
```

**Critical Design Decisions**:

| Decision | Rationale |
|----------|-----------|
| `retention.time=30d` | Balances storage cost with historical analysis needs |
| Read-only config mounts | Prevents accidental modification |
| Named volume for data | Persists metrics across container restarts |
| Health check endpoint | Enables orchestration and monitoring |

### 3. Scrape Mechanism

Prometheus uses a **pull model** (not push):

```mermaid
flowchart TD
    Start[Scrape Interval Triggered] --> SelectTarget[Select next target<br/>from scrape_configs]
    
    SelectTarget --> CheckHealth{Target<br/>healthy?}
    
    CheckHealth -->|No| MarkDown[Mark target as DOWN<br/>Record up=0]
    CheckHealth -->|Yes| Scrape[HTTP GET /metrics]
    
    Scrape --> Parse[Parse Prometheus format]
    Parse --> AddLabels[Add job and instance labels]
    AddLabels --> Store[Store in TSDB]
    
    MarkDown --> Next
    Store --> Next[Next target]
    
    Next --> Done{All targets<br/>scraped?}
    Done -->|No| SelectTarget
    Done -->|Yes| Wait[Wait for next interval]
    Wait --> Start
    
    style Scrape fill:#9f9,stroke:#333,stroke-width:2px
    style Store fill:#9cf,stroke:#333,stroke-width:2px
```

---

## Integration with Infrastructure

### manage.py Orchestration

The `infrastructure/manage.py` script manages Prometheus as a core service:

#### Service Definitions

```python
# From manage.py
CORE_SERVICES = [
    "redis-master",
    "zookeeper",
    "kafka",
    "nginx",
    "prometheus",   # ← Metrics collection (this component)
    "grafana"
]
```

Prometheus is a **core service**, meaning:
- Starts automatically with infrastructure
- Must be healthy before Grafana starts (dependency)
- Monitored for health continuously

#### Dependency Chain

```mermaid
graph LR
    subgraph "Service Dependencies"
        PROM[Prometheus]
        GRAF[Grafana]
    end
    
    PROM -->|depends_on| GRAF
    
    style PROM fill:#9cf,stroke:#333,stroke-width:3px
    style GRAF fill:#f9f,stroke:#333,stroke-width:2px
```

Grafana **depends on** Prometheus being healthy. This ensures:
1. Datasource is available when Grafana starts
2. Dashboards can query metrics immediately
3. Clean startup sequence

---

## Scrape Configuration

### Global Settings

```yaml
global:
  scrape_interval: 15s      # How often to scrape targets
  evaluation_interval: 15s  # How often to evaluate rules
  
  external_labels:
    environment: 'development'
    cluster: 'local'
    service: 'sse-streaming'
```

**Scrape Interval Trade-offs**:

| Interval | Pros | Cons | Best For |
|----------|------|------|----------|
| 5s | High resolution, fast detection | 3x storage, more load | Critical systems |
| **15s** | **Good balance** | **Standard choice** | **Most applications** |
| 30s | Lower storage, less load | Slower detection | Low-traffic apps |
| 60s | Minimal storage | Very slow detection | Batch jobs |

### Scrape Targets

#### 1. SSE Application Instances

```yaml
scrape_configs:
  - job_name: 'sse-application'
    static_configs:
      - targets:
          - 'app-1:8000'
          - 'app-2:8000'
          - 'app-3:8000'
    metrics_path: '/admin/metrics'
    scrape_interval: 15s
```

**What Gets Scraped**:

```mermaid
graph LR
    PROM[Prometheus] -->|GET /admin/metrics| APP1[app-1:8000]
    PROM -->|GET /admin/metrics| APP2[app-2:8000]
    PROM -->|GET /admin/metrics| APP3[app-3:8000]
    
    APP1 --> M1[sse_requests_total<br/>sse_request_duration_seconds<br/>sse_active_connections<br/>...]
    APP2 --> M2[sse_requests_total<br/>sse_request_duration_seconds<br/>sse_active_connections<br/>...]
    APP3 --> M3[sse_requests_total<br/>sse_request_duration_seconds<br/>sse_active_connections<br/>...]
```

#### 2. NGINX Metrics

```yaml
- job_name: 'nginx'
  static_configs:
    - targets: ['nginx:80']
  metrics_path: '/nginx-status'
```

#### 3. Redis Metrics

```yaml
- job_name: 'redis'
  static_configs:
    - targets: ['redis-exporter:9121']
  metrics_path: '/metrics'
```

### Metric Labels

Every metric automatically gets these labels:

```promql
sse_requests_total{
  job="sse-application",           # From scrape config
  instance="app-1:8000",            # Target address
  environment="development",        # External label
  cluster="local",                  # External label
  service="sse-streaming",          # External label
  status="success"                  # Application-defined label
}
```

**Label Hierarchy**:

```mermaid
graph TD
    Metric[Metric Name<br/>sse_requests_total] --> Job[job label<br/>sse-application]
    Job --> Instance[instance label<br/>app-1:8000]
    Instance --> External[External labels<br/>environment, cluster, service]
    External --> App[Application labels<br/>status, endpoint, method]
    
    style Metric fill:#f9f,stroke:#333,stroke-width:2px
    style Job fill:#9cf,stroke:#333,stroke-width:2px
    style Instance fill:#9cf,stroke:#333,stroke-width:2px
    style External fill:#ff9,stroke:#333,stroke-width:2px
    style App fill:#9f9,stroke:#333,stroke-width:2px
```

---

## Metrics and Labels

### Key Metrics Collected

#### Application Metrics

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `sse_requests_total` | Counter | Total requests received | `status`, `endpoint`, `method` |
| `sse_request_duration_seconds` | Histogram | Request latency distribution | `endpoint`, `method` |
| `sse_active_connections` | Gauge | Current active SSE connections | `instance` |
| `sse_cache_hits_total` | Counter | Cache hit count | `tier` (L1/L2) |
| `sse_cache_misses_total` | Counter | Cache miss count | `tier` (L1/L2) |

#### NGINX Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `nginx_connections_active` | Gauge | Active client connections |
| `nginx_connections_reading` | Gauge | Connections reading request |
| `nginx_connections_writing` | Gauge | Connections writing response |
| `nginx_connections_waiting` | Gauge | Idle keepalive connections |

#### Redis Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `redis_connected_clients` | Gauge | Number of connected clients |
| `redis_used_memory_bytes` | Gauge | Memory used by Redis |
| `redis_commands_processed_total` | Counter | Total commands processed |

### Metric Types Explained

```mermaid
graph TB
    subgraph "Counter"
        C1[Value: 0] -->|Increment| C2[Value: 1]
        C2 -->|Increment| C3[Value: 2]
        C3 -->|Increment| C4[Value: 3]
        Note1[Only goes up<br/>Resets on restart]
    end
    
    subgraph "Gauge"
        G1[Value: 5] -->|Set| G2[Value: 8]
        G2 -->|Set| G3[Value: 3]
        G3 -->|Set| G4[Value: 10]
        Note2[Can go up or down<br/>Represents current state]
    end
    
    subgraph "Histogram"
        H1[Bucket: 0-0.1s: 50] 
        H2[Bucket: 0.1-0.5s: 30]
        H3[Bucket: 0.5-1s: 15]
        H4[Bucket: 1s+: 5]
        Note3[Distribution of values<br/>Enables percentiles]
    end
    
    style C4 fill:#9f9
    style G4 fill:#9cf
    style Note3 fill:#ff9
```

---

## Alerting Rules

### Alert Rule Structure

```yaml
groups:
  - name: sse_application
    interval: 15s
    rules:
      - alert: HighErrorRate
        expr: |
          (
            sum(rate(sse_requests_total{status!="success"}[5m]))
            /
            sum(rate(sse_requests_total[5m]))
          ) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }}"
```

### Alert Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Inactive: Rule defined
    
    Inactive --> Pending: Condition becomes true
    note right of Pending
        Waiting for "for" duration
        (e.g., 2 minutes)
    end note
    
    Pending --> Inactive: Condition becomes false
    Pending --> Firing: "for" duration elapsed
    
    note right of Firing
        Alert is active
        Sent to Alertmanager
    end note
    
    Firing --> Inactive: Condition becomes false
    Firing --> Resolved: Condition false for resolve_time
    
    Resolved --> Inactive
```

### Example Alerts

#### 1. High Error Rate

```yaml
- alert: HighErrorRate
  expr: |
    (sum(rate(sse_requests_total{status!="success"}[5m])) 
     / sum(rate(sse_requests_total[5m]))) > 0.05
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Error rate above 5%"
```

**When It Fires**: Error rate > 5% for 2 consecutive minutes

#### 2. High P95 Latency

```yaml
- alert: HighP95Latency
  expr: |
    histogram_quantile(0.95, 
      sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
    ) > 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "P95 latency above 2 seconds"
```

**When It Fires**: 95th percentile latency > 2s for 5 minutes

#### 3. Low Cache Hit Rate

```yaml
- alert: LowCacheHitRate
  expr: |
    (sum(rate(sse_cache_hits_total{tier="L2"}[10m]))
     / (sum(rate(sse_cache_hits_total{tier="L2"}[10m])) 
        + sum(rate(sse_cache_misses_total{tier="L2"}[10m])))) < 0.5
  for: 10m
  labels:
    severity: info
  annotations:
    summary: "L2 cache hit rate below 50%"
```

**When It Fires**: L2 cache hit rate < 50% for 10 minutes

---

## Troubleshooting

### Common Issues

#### 1. Target Down

**Symptom**: Prometheus shows target as "DOWN" in `/targets` page

**Diagnosis**:

```mermaid
flowchart TD
    Start[Target shows DOWN] --> CheckTarget{Is target<br/>service running?}
    
    CheckTarget -->|No| StartTarget[Start service:<br/>docker compose up -d]
    CheckTarget -->|Yes| CheckPort{Is port<br/>accessible?}
    
    CheckPort -->|No| CheckFirewall[Check firewall/<br/>network settings]
    CheckPort -->|Yes| CheckEndpoint{Does /metrics<br/>endpoint exist?}
    
    CheckEndpoint -->|No| FixApp[Add metrics endpoint<br/>to application]
    CheckEndpoint -->|Yes| CheckFormat{Is format<br/>valid?}
    
    CheckFormat -->|No| FixFormat[Fix Prometheus<br/>format output]
    CheckFormat -->|Yes| CheckConfig[Check prometheus.yml<br/>scrape config]
    
    style StartTarget fill:#f99
    style FixApp fill:#f99
    style FixFormat fill:#f99
```

**Solution**:
```bash
# Check if target is running
docker compose ps app-1

# Test metrics endpoint manually
curl http://app-1:8000/admin/metrics

# Check Prometheus logs
docker compose logs prometheus --tail=50
```

#### 2. No Data in Grafana

**Symptom**: Grafana dashboards show "No data"

**Diagnosis**:

| Check | Command | What to Look For |
|-------|---------|------------------|
| Prometheus health | `curl http://localhost:9090/-/healthy` | Should return "Prometheus is Healthy" |
| Targets status | Visit http://localhost:9090/targets | All targets should be "UP" |
| Query metrics | `curl 'http://localhost:9090/api/v1/query?query=up'` | Should return data |
| Grafana datasource | Check Grafana datasource settings | URL should be `http://prometheus:9090` |

#### 3. High Memory Usage

**Symptom**: Prometheus container using excessive memory

**Causes & Solutions**:

| Cause | Solution |
|-------|----------|
| Too many metrics | Reduce scrape targets or increase `scrape_interval` |
| Long retention | Reduce `storage.tsdb.retention.time` |
| High cardinality labels | Avoid labels with many unique values |
| Memory leaks | Restart Prometheus, upgrade to latest version |

**Monitoring Memory**:
```bash
# Check Prometheus memory usage
docker stats prometheus

# Check TSDB size
docker compose exec prometheus du -sh /prometheus
```

---

## Query Examples

### PromQL Basics

#### Request Rate

```promql
# Requests per second (last 5 minutes)
rate(sse_requests_total[5m])

# Total requests per second across all instances
sum(rate(sse_requests_total[5m]))

# Requests per second by instance
sum(rate(sse_requests_total[5m])) by (instance)
```

#### Error Rate

```promql
# Error rate as percentage
(
  sum(rate(sse_requests_total{status!="success"}[5m]))
  /
  sum(rate(sse_requests_total[5m]))
) * 100
```

#### Latency Percentiles

```promql
# P50 latency
histogram_quantile(0.50, 
  sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
)

# P95 latency
histogram_quantile(0.95, 
  sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
)

# P99 latency
histogram_quantile(0.99, 
  sum(rate(sse_request_duration_seconds_bucket[5m])) by (le)
)
```

#### Cache Hit Rate

```promql
# L2 cache hit rate
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

---

## Performance Tuning

### Storage Optimization

```yaml
# In docker-compose.yml command section
--storage.tsdb.retention.time=30d      # Keep 30 days
--storage.tsdb.retention.size=10GB     # Or max 10GB
```

**Retention Trade-offs**:

| Retention | Storage | Use Case |
|-----------|---------|----------|
| 7d | ~2GB | Development, testing |
| 15d | ~4GB | Short-term production |
| **30d** | **~8GB** | **Standard production** |
| 90d | ~24GB | Compliance, long-term analysis |

### Scrape Optimization

```yaml
# Reduce load on high-cardinality targets
scrape_configs:
  - job_name: 'expensive-target'
    scrape_interval: 30s  # Slower than global 15s
    scrape_timeout: 10s   # Longer timeout
```

---

## Quick Reference

### Access URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Prometheus UI | http://localhost:9090 | Query interface, target status |
| Targets | http://localhost:9090/targets | View scrape target health |
| Alerts | http://localhost:9090/alerts | View active alerts |
| Graph | http://localhost:9090/graph | Execute PromQL queries |
| Metrics | http://localhost:9090/metrics | Prometheus's own metrics |

### Common Commands

```bash
# Start infrastructure (including Prometheus)
python infrastructure/manage.py start

# Restart just Prometheus
python infrastructure/manage.py restart --services prometheus

# View Prometheus logs
docker compose logs prometheus --tail=50 --follow

# Check configuration syntax
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml

# Check alert rules syntax
docker compose exec prometheus promtool check rules /etc/prometheus/alerts/*.yml

# Query metrics via CLI
docker compose exec prometheus promtool query instant http://localhost:9090 'up'
```

---

## Professional Standards

This Prometheus setup demonstrates:

✅ **Comprehensive Monitoring**: Metrics from all critical components  
✅ **Efficient Storage**: Optimized retention and scrape intervals  
✅ **Proactive Alerting**: Alert rules for common failure modes  
✅ **High Availability**: Health checks and automatic recovery  
✅ **Observability**: Full visibility into system behavior  
✅ **Best Practices**: Industry-standard configuration patterns  
✅ **Documentation**: Extensively commented configuration  

---

## Further Reading

- [Prometheus Official Documentation](https://prometheus.io/docs/introduction/overview/)
- [PromQL Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Best Practices](https://prometheus.io/docs/practices/naming/)
- [Metric Types](https://prometheus.io/docs/concepts/metric_types/)
