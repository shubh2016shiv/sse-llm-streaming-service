# Grafana Monitoring Infrastructure

**Professional monitoring and visualization for the SSE Streaming Application**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Directory Structure](#directory-structure)
4. [How It Works](#how-it-works)
5. [Integration with Infrastructure](#integration-with-infrastructure)
6. [Configuration Deep Dive](#configuration-deep-dive)
7. [Troubleshooting](#troubleshooting)

---

## Overview

This directory contains the complete Grafana monitoring stack for the SSE application. Grafana provides real-time visualization of metrics collected by Prometheus, enabling you to monitor application health, performance, and user behavior through pre-configured dashboards.

### Key Features

- **Automatic Provisioning**: Dashboards and datasources are configured automatically on startup
- **Infrastructure as Code**: All configurations are version-controlled and reproducible
- **Zero Manual Setup**: No clicking through UIs required
- **Production-Ready**: Follows industry best practices for observability

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph "SSE Application"
        APP1[App Instance 1<br/>:8000]
        APP2[App Instance 2<br/>:8000]
        APP3[App Instance 3<br/>:8000]
    end
    
    subgraph "Monitoring Stack"
        PROM[Prometheus<br/>:9090]
        GRAF[Grafana<br/>:3000]
    end
    
    subgraph "User"
        USER[Developer/Ops]
    end
    
    APP1 -->|Expose /metrics| PROM
    APP2 -->|Expose /metrics| PROM
    APP3 -->|Expose /metrics| PROM
    
    PROM -->|Scrape every 15s| PROM
    GRAF -->|Query metrics| PROM
    USER -->|View dashboards| GRAF
    
    style GRAF fill:#f9f,stroke:#333,stroke-width:2px
    style PROM fill:#9cf,stroke:#333,stroke-width:2px
```

### Data Flow

```mermaid
sequenceDiagram
    participant App as SSE Application
    participant Prom as Prometheus
    participant Graf as Grafana
    participant User as Developer
    
    Note over App: Application exposes<br/>/metrics endpoint
    
    loop Every 15 seconds
        Prom->>App: HTTP GET /metrics
        App-->>Prom: Metrics (Prometheus format)
        Note over Prom: Store time-series data
    end
    
    User->>Graf: Open dashboard
    Graf->>Prom: PromQL query
    Prom-->>Graf: Time-series data
    Graf-->>User: Rendered visualization
```

---

## Directory Structure

```
infrastructure/grafana/
├── README.md                           # This file
├── dashboards/                         # Dashboard Templates (JSON)
│   └── sse-overview.json              # Main application dashboard
└── provisioning/                       # Auto-configuration
    ├── datasources/
    │   └── prometheus.yml             # Prometheus connection config
    └── dashboards/
        └── config.yml                 # Dashboard loading config
```

### File Purposes

| File | Purpose | When It's Used |
|------|---------|----------------|
| `dashboards/sse-overview.json` | Dashboard blueprint defining panels, queries, and layout | Loaded by Grafana on startup via provisioning |
| `provisioning/datasources/prometheus.yml` | Configures Prometheus as a datasource | Read by Grafana during startup |
| `provisioning/dashboards/config.yml` | Tells Grafana where to find dashboard JSON files | Read by Grafana during startup |

---

## How It Works

### 1. Infrastructure Startup Sequence

When you run `python infrastructure/manage.py start`, here's what happens:

```mermaid
sequenceDiagram
    participant User
    participant ManagePy as manage.py
    participant Docker as Docker Compose
    participant Grafana
    participant Prom as Prometheus
    
    User->>ManagePy: python manage.py start
    
    Note over ManagePy: Pre-flight checks<br/>(Docker available?)
    
    ManagePy->>Docker: docker compose up -d
    
    Note over Docker: Start services in order
    
    Docker->>Prom: Start Prometheus
    Note over Prom: Load prometheus.yml<br/>Start scraping targets
    
    Docker->>Grafana: Start Grafana
    
    Note over Grafana: 1. Read provisioning configs
    
    Grafana->>Grafana: Load datasources/<br/>prometheus.yml
    Note over Grafana: 2. Connect to Prometheus
    
    Grafana->>Grafana: Load dashboards/<br/>config.yml
    Note over Grafana: 3. Scan /dashboards/<br/>for JSON files
    
    Grafana->>Grafana: Import sse-overview.json
    Note over Grafana: 4. Dashboard ready!
    
    ManagePy->>Docker: Check health
    Docker-->>ManagePy: All healthy
    ManagePy-->>User: ✅ Infrastructure ready
```

### 2. Docker Compose Integration

The `docker-compose.yml` file defines how Grafana runs and what it has access to:

```yaml
grafana:
  image: grafana/grafana:10.2.2
  ports:
    - "3000:3000"
  
  volumes:
    # Mount entire provisioning directory
    - ./infrastructure/grafana/provisioning:/etc/grafana/provisioning:ro
    
    # Mount dashboard templates
    - ./infrastructure/grafana/dashboards:/etc/grafana/dashboards:ro
    
    # Persistent storage
    - grafana-data:/var/lib/grafana
```

**Critical Design Decision**: We mount the **entire** `provisioning/` directory, not individual files. This is because Grafana's provisioning system scans subdirectories (`datasources/`, `dashboards/`) for configuration files. File-level mounts would break this scanning mechanism.

### 3. Provisioning System

Grafana's provisioning system follows this logic:

```mermaid
flowchart TD
    Start[Grafana Starts] --> ScanProv[Scan /etc/grafana/provisioning/]
    
    ScanProv --> ScanDS[Scan datasources/ subdirectory]
    ScanDS --> LoadDS[Load all *.yml files]
    LoadDS --> ConnectDS[Connect to datasources]
    
    ScanProv --> ScanDash[Scan dashboards/ subdirectory]
    ScanDash --> LoadDashConfig[Load dashboard configs]
    LoadDashConfig --> ReadPath{Read 'path' from config}
    ReadPath --> ScanDashFiles[Scan path for *.json files]
    ScanDashFiles --> ImportDash[Import dashboards]
    
    ConnectDS --> Ready[Grafana Ready]
    ImportDash --> Ready
    
    style Ready fill:#9f9,stroke:#333,stroke-width:2px
```

---

## Integration with Infrastructure

### manage.py Orchestration

The `infrastructure/manage.py` script orchestrates the entire infrastructure lifecycle:

#### Service Definitions

```python
# From manage.py
CORE_SERVICES = [
    "redis-master",
    "zookeeper", 
    "kafka",
    "nginx",
    "prometheus",  # ← Metrics collection
    "grafana"      # ← Visualization
]
```

Grafana is a **core service**, meaning it starts automatically with the infrastructure.

#### Startup Flow

| Step | Action | Command | What Happens |
|------|--------|---------|--------------|
| 1 | Pre-flight Check | `_preflight_check()` | Validates Docker is available |
| 2 | Start Services | `docker compose up -d` | Starts all core services |
| 3 | Wait for Health | `_wait_for_healthy()` | Polls health endpoints |
| 4 | Display Status | `_display_status()` | Shows service URLs |

#### Health Monitoring

```python
# Grafana health check (from docker-compose.yml)
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", 
         "http://localhost:3000/api/health"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 30s
```

The health check ensures Grafana is fully operational before `manage.py` reports success.

### Service Dependencies

```mermaid
graph LR
    subgraph "Dependency Chain"
        PROM[Prometheus]
        GRAF[Grafana]
    end
    
    PROM -->|depends_on| GRAF
    
    style PROM fill:#9cf
    style GRAF fill:#f9f
```

Grafana depends on Prometheus being healthy before it starts. This ensures the datasource is available when Grafana tries to connect.

---

## Configuration Deep Dive

### Datasource Configuration

**File**: `provisioning/datasources/prometheus.yml`

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    uid: prometheus          # ← Critical: Dashboards reference this UID
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

**Key Fields**:

| Field | Value | Why It Matters |
|-------|-------|----------------|
| `uid` | `prometheus` | Dashboards use this to reference the datasource. Must be explicit. |
| `url` | `http://prometheus:9090` | Uses Docker Compose service name (not `localhost`) |
| `access` | `proxy` | Grafana proxies requests (secure, avoids CORS) |
| `isDefault` | `true` | Default datasource for new panels |
| `editable` | `false` | Prevents accidental UI changes (config is source of truth) |

### Dashboard Configuration

**File**: `provisioning/dashboards/config.yml`

```yaml
apiVersion: 1

providers:
  - name: 'SSE Dashboards'
    orgId: 1
    folder: 'SSE Streaming'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/dashboards
      foldersFromFilesStructure: true
```

**Key Fields**:

| Field | Value | Explanation |
|-------|-------|-------------|
| `folder` | `'SSE Streaming'` | Dashboards appear under this folder in Grafana UI |
| `path` | `/etc/grafana/dashboards` | Container path where JSON files are located |
| `updateIntervalSeconds` | `10` | Grafana checks for new/updated dashboards every 10s |
| `allowUiUpdates` | `true` | You can edit dashboards in UI (changes won't persist) |
| `foldersFromFilesStructure` | `true` | Subdirectories become folders in Grafana |

### Dashboard Template

**File**: `dashboards/sse-overview.json`

This is a **declarative blueprint** defining:
- Panel layout (rows, columns, sizes)
- PromQL queries for each metric
- Visualization types (graphs, gauges, stats)
- Thresholds and alerts
- Design rationale (embedded in descriptions)

**Portfolio Feature**: This dashboard includes educational comments explaining *why* specific metrics were chosen (RED method, Golden Signals), demonstrating architectural understanding.

---

## Troubleshooting

### Dashboard Shows "No data"

**Symptom**: Dashboard loads but panels show "No data"

**Diagnosis**:
```mermaid
flowchart TD
    Start[No Data in Dashboard] --> CheckApp{Are app instances<br/>running?}
    
    CheckApp -->|No| StartApp[Start app instances:<br/>manage.py start --all]
    CheckApp -->|Yes| CheckMetrics{Do apps expose<br/>/metrics endpoint?}
    
    CheckMetrics -->|No| FixApp[Fix application<br/>metrics endpoint]
    CheckMetrics -->|Yes| CheckProm{Is Prometheus<br/>scraping?}
    
    CheckProm -->|No| CheckPromConfig[Check prometheus.yml<br/>scrape configs]
    CheckProm -->|Yes| CheckQuery{Are PromQL<br/>queries correct?}
    
    CheckQuery -->|No| FixQuery[Update dashboard<br/>queries]
    CheckQuery -->|Yes| CheckTime{Check time range<br/>in dashboard}
    
    style StartApp fill:#f99
    style FixApp fill:#f99
    style CheckPromConfig fill:#f99
    style FixQuery fill:#f99
    style CheckTime fill:#9f9
```

**Solution**:
1. Verify app instances are running: `docker compose ps`
2. Check Prometheus targets: http://localhost:9090/targets
3. Verify metrics are being collected: http://localhost:9090/graph

### Dashboard Not Appearing

**Symptom**: Grafana shows "No dashboards yet"

**Root Cause**: Provisioning failed

**Diagnosis**:
```bash
# Check Grafana logs
docker compose logs grafana --tail=50

# Look for these lines:
# ✅ GOOD: "logger=provisioning.dashboard ... msg='provisioning dashboards'"
# ❌ BAD:  "logger=provisioning.dashboard ... error='no such file or directory'"
```

**Common Causes**:

| Error | Cause | Fix |
|-------|-------|-----|
| `no such file or directory` | Volume mount incorrect | Verify docker-compose.yml mounts |
| `failed to load dashboard` | Invalid JSON | Validate JSON syntax |
| `dashboard already exists` | UID conflict | Change dashboard UID |

### Datasource Connection Failed

**Symptom**: Dashboard shows "Failed to retrieve datasource"

**Diagnosis**:
```bash
# Check if Prometheus is running
docker compose ps prometheus

# Check Grafana can reach Prometheus
docker compose exec grafana wget -O- http://prometheus:9090/-/healthy
```

**Solution**:
1. Ensure Prometheus is healthy: `docker compose ps`
2. Verify datasource UID matches dashboard references
3. Check `provisioning/datasources/prometheus.yml` URL is correct

---

## Quick Reference

### Access URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | None |
| SSE Dashboard | http://localhost:3000/d/sse-overview | admin / admin |

### Common Commands

```bash
# Start infrastructure (including Grafana)
python infrastructure/manage.py start

# Start everything (including app instances)
python infrastructure/manage.py start --all

# Restart just Grafana
python infrastructure/manage.py restart --services grafana

# Stop infrastructure
python infrastructure/manage.py stop

# View Grafana logs
docker compose logs grafana --tail=50 --follow
```

### File Modification Workflow

```mermaid
flowchart LR
    Edit[Edit dashboard JSON<br/>or provisioning config] --> Restart[Restart Grafana]
    Restart --> Verify[Verify in browser]
    
    Restart -.->|Alternative| Wait[Wait 10 seconds<br/>for auto-reload]
    Wait --> Verify
    
    style Edit fill:#9cf
    style Verify fill:#9f9
```

**Note**: Dashboard provisioning checks for updates every 10 seconds. For immediate effect, restart Grafana.

---

## Professional Standards

This Grafana setup demonstrates:

✅ **Infrastructure as Code**: All configurations version-controlled  
✅ **Declarative Configuration**: Desired state defined, not imperative steps  
✅ **Automatic Provisioning**: Zero manual setup required  
✅ **Dependency Management**: Services start in correct order  
✅ **Health Monitoring**: Automated health checks ensure reliability  
✅ **Observability**: Comprehensive monitoring from day one  
✅ **Documentation**: Self-documenting architecture with inline explanations

---

## Further Reading

- [Grafana Provisioning Documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Prometheus Query Language (PromQL)](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [RED Method for Monitoring](https://www.weave.works/blog/the-red-method-key-metrics-for-microservices-architecture/)
- [Google SRE Book - Monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)

