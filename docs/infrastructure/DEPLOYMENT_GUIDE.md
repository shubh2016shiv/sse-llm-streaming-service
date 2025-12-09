# SSE Streaming Application - Deployment Guide

## Quick Start

### Prerequisites
- Docker Desktop installed and running
- At least 4GB RAM available
- Ports available: 80, 3000, 8081, 8082, 9090, 9121
- `.env` file with API keys (see Configuration section)

### Start the Infrastructure

```bash
# Navigate to project directory
cd "d:\Generative AI Portfolio Projects\SSE"

# Start all services
docker-compose up -d

# Wait for services to be healthy (30-60 seconds)
docker-compose ps

# Check logs if needed
docker-compose logs -f
```

### Verify Deployment

1. **Application Health**
   ```bash
   curl http://localhost/health
   ```
   Expected: `{"status":"healthy",...}`

2. **Load Balancer**
   ```bash
   curl http://localhost/nginx-health
   ```
   Expected: `NGINX is healthy`

3. **Prometheus**
   - Open: http://localhost:9090
   - Go to Status → Targets
   - Verify all targets are "UP"

4. **Grafana**
   - Open: http://localhost:3000
   - Login: admin/admin
   - Change password when prompted
   - Navigate to Dashboards

### Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| Application | http://localhost | N/A |
| Grafana | http://localhost:3000 | admin/admin |
| Prometheus | http://localhost:9090 | N/A |
| Redis Commander | http://localhost:8081 | N/A |
| Kafka UI | http://localhost:8082 | N/A |

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
# LLM Provider API Keys
OPENAI_API_KEY=sk-your-key-here
DEEPSEEK_API_KEY=your-key-here
GOOGLE_API_KEY=your-key-here

# Application Settings
ENVIRONMENT=development
LOG_LEVEL=INFO
DEBUG=false

# Redis Settings
REDIS_HOST=redis-master
REDIS_PORT=6379

# Circuit Breaker
CB_FAILURE_THRESHOLD=5
CB_RECOVERY_TIMEOUT=60

# Rate Limiting
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_PREMIUM=1000/minute

# Cache
CACHE_RESPONSE_TTL=3600
CACHE_SESSION_TTL=86400

# Queue
QUEUE_TYPE=redis
```

## Testing the Deployment

### 1. Test Load Balancer Distribution

```bash
# Make multiple requests
for i in {1..10}; do
  curl -s http://localhost/ | jq -r '.version'
done

# Check NGINX logs to see distribution
docker-compose logs nginx | grep "upstream"
```

### 2. Test SSE Streaming

```bash
# Run verification script
python verify_streaming_real.py

# Or manual test
curl -N -X POST http://localhost/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Hello, how are you?","model":"gpt-4"}'
```

### 3. Monitor in Grafana

1. Open Grafana: http://localhost:3000
2. Go to Dashboards → SSE Overview
3. Run load test:
   ```bash
   cd performance_experiments
   python run_load_test.py --url http://localhost --concurrency 10 --duration 60
   ```
4. Watch metrics update in real-time

### 4. Test Failover

```bash
# Stop one app instance
docker-compose stop app-1

# Make requests (should still work)
curl http://localhost/health

# Check NGINX marks instance as down
docker-compose logs nginx | grep "app-1"

# Restart instance
docker-compose start app-1

# Verify it rejoins pool
curl http://localhost/nginx-status
```

## Scaling

### Add More App Instances

1. Edit `docker-compose.yml`:
   ```yaml
   app-4:
     # Copy app-1 configuration
     # Change container_name to sse-app-4
     # Change hostname to app-4
   ```

2. Edit `infrastructure/nginx/nginx.conf`:
   ```nginx
   upstream sse_backend {
       least_conn;
       server app-1:8000 max_fails=3 fail_timeout=30s;
       server app-2:8000 max_fails=3 fail_timeout=30s;
       server app-3:8000 max_fails=3 fail_timeout=30s;
       server app-4:8000 max_fails=3 fail_timeout=30s;  # Add this
   }
   ```

3. Restart:
   ```bash
   docker-compose up -d
   ```

## Troubleshooting

### Services Won't Start

```bash
# Check Docker is running
docker info

# Check port conflicts
netstat -ano | findstr "80"
netstat -ano | findstr "3000"
netstat -ano | findstr "9090"

# View detailed logs
docker-compose logs [service-name]
```

### NGINX 502 Bad Gateway

```bash
# Check app instances are healthy
docker-compose ps

# Check app logs
docker-compose logs app-1
docker-compose logs app-2
docker-compose logs app-3

# Check NGINX can reach apps
docker-compose exec nginx ping app-1
```

### Prometheus Not Scraping

```bash
# Check Prometheus config
docker-compose exec prometheus cat /etc/prometheus/prometheus.yml

# Check Prometheus logs
docker-compose logs prometheus

# Verify targets in UI
# http://localhost:9090/targets
```

### Grafana No Data

```bash
# Check Prometheus data source
# Grafana → Configuration → Data Sources

# Test connection
# Click "Test" button on Prometheus data source

# Check Prometheus has data
# http://localhost:9090/graph
# Query: up
```

## Stopping the Infrastructure

### Stop All Services

```bash
docker-compose down
```

### Stop and Remove Data (CAUTION)

```bash
# This deletes all volumes (Prometheus data, Grafana dashboards, etc.)
docker-compose down -v
```

### Stop Specific Service

```bash
docker-compose stop [service-name]
```

## Maintenance

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app-1

# Last 100 lines
docker-compose logs --tail=100 nginx
```

### Restart Service

```bash
docker-compose restart [service-name]
```

### Update Configuration

```bash
# After editing config files
docker-compose up -d --force-recreate [service-name]

# Reload NGINX config (no downtime)
docker-compose exec nginx nginx -s reload

# Reload Prometheus config (no downtime)
curl -X POST http://localhost:9090/-/reload
```

### Backup Data

```bash
# Backup Prometheus data
docker run --rm -v sse_prometheus-data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus-backup.tar.gz /data

# Backup Grafana data
docker run --rm -v sse_grafana-data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz /data
```

## Production Considerations

### Security

1. **Change Default Passwords**
   - Grafana: admin/admin → strong password
   - Add authentication to Prometheus

2. **Enable HTTPS**
   - Add SSL certificates to NGINX
   - Configure SSL termination

3. **Restrict Access**
   - Use firewall rules
   - Limit Prometheus/Grafana to internal network
   - Add authentication to admin endpoints

### Performance

1. **Resource Limits**
   - Add memory/CPU limits to docker-compose
   - Monitor resource usage

2. **Optimize Prometheus**
   - Adjust retention period based on needs
   - Use recording rules for expensive queries

3. **Scale Horizontally**
   - Add more app instances
   - Use external load balancer (AWS ALB, etc.)

### Monitoring

1. **Set Up Alerts**
   - Configure Alertmanager
   - Add notification channels (Slack, email, PagerDuty)

2. **Dashboard Customization**
   - Create team-specific dashboards
   - Add business metrics

3. **Log Aggregation**
   - Consider ELK stack or Loki
   - Centralize logs from all instances

## Next Steps

1. **Explore Grafana Dashboards**
   - SSE Overview: High-level metrics
   - SSE Detailed: Deep-dive debugging

2. **Set Up Alerts**
   - Review alert rules in Prometheus
   - Configure Alertmanager

3. **Performance Testing**
   - Run load tests
   - Tune based on results

4. **Production Deployment**
   - Follow production considerations above
   - Set up CI/CD pipeline
   - Implement blue-green deployment

## Support

For issues or questions:
1. Check logs: `docker-compose logs [service]`
2. Review documentation in `docs/infrastructure/`
3. Check Prometheus alerts: http://localhost:9090/alerts
4. Review Grafana dashboards for anomalies
