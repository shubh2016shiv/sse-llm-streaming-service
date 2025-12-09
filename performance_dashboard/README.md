# Performance Dashboard

A modern, real-time performance monitoring dashboard for the SSE Streaming Microservice. Built with React, Vite, and Recharts to visualize execution statistics, manage configurations, and conduct load testing.

## Features

- **Real-time Monitoring**: View execution statistics by processing stage (p50, p90, p95, p99 percentiles)
- **Configuration Management**: Update runtime settings (fake LLM, caching, queue type)
- **Load Testing**: Run concurrent load tests with configurable parameters
- **Interactive UI**: Toggle switches, live charts, and responsive design
- **Docker-Ready**: Fully containerized with nginx for production deployment

## Architecture

```
Browser (Port 3001) 
    ↓
Performance Dashboard (nginx container)
    ↓
SSE Backend Network (sse-network)
    ↓
NGINX Load Balancer (sse-nginx)
    ↓
Backend API (app-1, app-2, app-3)
```

## Prerequisites

- **Docker** & **Docker Compose** installed
- **SSE Backend** running (see main project README)
- Node.js 20+ (for local development only)

## Quick Start

### Option 1: Docker Deployment (Recommended)

1. **Ensure backend is running:**
   ```bash
   cd ..
   docker-compose ps
   ```
   All services should show "Up" status.

2. **Start the dashboard:**
   ```bash
   docker-compose up -d
   ```

3. **Access the dashboard:**
   ```
   http://localhost:3001
   ```

4. **View logs:**
   ```bash
   docker-compose logs -f
   ```

5. **Stop the dashboard:**
   ```bash
   docker-compose down
   ```

### Option 2: Local Development

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Start development server:**
   ```bash
   npm run dev
   ```

3. **Access the dashboard:**
   ```
   http://localhost:5173
   ```

The development server includes hot module replacement for instant updates.

## Configuration

### Environment Variables

The dashboard uses environment variables to configure the API endpoint:

| Variable | Description | Default | Docker Value |
|----------|-------------|---------|--------------|
| `VITE_API_BASE_URL` | SSE backend API URL | `http://localhost:8000` | `http://sse-nginx` |

**Development Mode:**
- Uses `http://localhost:8000` (your local backend)
- No environment variable needed

**Docker Mode:**
- Set in `docker-compose.yml`
- Uses Docker networking to reach backend

### Customizing API Endpoint

Edit `docker-compose.yml` to change the API endpoint:

```yaml
environment:
  # Option 1: Use load balancer (recommended)
  - VITE_API_BASE_URL=http://sse-nginx

  # Option 2: Direct to specific app instance
  - VITE_API_BASE_URL=http://sse-app-1:8000

  # Option 3: Use host machine
  - VITE_API_BASE_URL=http://host.docker.internal:8000
```

## Docker Configuration

### Dockerfile

Multi-stage build for optimal image size:

**Stage 1 (Builder):**
- Node.js 20-alpine
- Installs dependencies and builds React app
- Output: `/app/dist`

**Stage 2 (Production):**
- Nginx 1.25-alpine
- Serves static files
- Final image: ~25MB

### docker-compose.yml

Standalone configuration that:
- Builds dashboard image
- Connects to external `sse-network`
- Exposes port 3001
- Includes health checks

### nginx.conf

Dashboard-specific nginx configuration:
- SPA fallback routing
- Gzip compression
- Cache headers for static assets
- Health check endpoint at `/health`

## API Integration

The dashboard consumes the following SSE backend endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/admin/execution-stats` | GET | Fetch execution statistics by stage |
| `/admin/config` | GET | Retrieve current configuration |
| `/admin/config` | PUT | Update runtime configuration |
| `/stream` | POST | Stream LLM responses (for load testing) |

### Example: Fetch Statistics

```javascript
import { getStats } from './api';

const stats = await getStats();
// Returns: { "1": { avg_time, count, ... }, "2": { ... }, ... }
```

### Example: Update Configuration

```javascript
import { updateConfig } from './api';

await updateConfig({
  USE_FAKE_LLM: true,
  ENABLE_CACHING: false
});
```

## Troubleshooting

### Dashboard can't connect to backend

**Symptoms:**
- Network errors in browser console
- API requests fail
- "Failed to fetch" errors

**Solutions:**

1. **Check backend is running:**
   ```bash
   cd ..
   docker-compose ps
   ```

2. **Verify network exists:**
   ```bash
   docker network ls | grep sse-network
   ```

3. **Test connectivity from dashboard container:**
   ```bash
   docker exec performance-dashboard wget -O- http://sse-nginx/health
   ```

4. **Check VITE_API_BASE_URL:**
   ```bash
   docker-compose config | grep VITE_API_BASE_URL
   ```

### Network not found error

**Error:**
```
network sse-network declared as external, but could not be found
```

**Solution:**
Start the SSE backend first to create the network:
```bash
cd ..
docker-compose up -d
```

### CORS errors

**Error:**
```
Access to fetch at 'http://sse-nginx/admin/config' from origin 'http://localhost:3001' 
has been blocked by CORS policy
```

**Solution:**
The backend is already configured to allow all origins. This error usually indicates:
- Backend is not running
- Wrong API URL in environment variable
- Network connectivity issue

### Build errors

**Error:**
```
npm ERR! peer dependency conflicts
```

**Solution:**
The Dockerfile uses `npm ci --legacy-peer-deps` to handle this automatically.
For local development:
```bash
npm install --legacy-peer-deps
```

## Development

### Project Structure

```
performance_dashboard/
├── src/
│   ├── components/         # React components
│   │   ├── ConfigPanel.jsx
│   │   ├── LoadTestPanel.jsx
│   │   └── StatsPanel.jsx
│   ├── api.js             # API client
│   ├── App.jsx            # Main app component
│   ├── main.jsx           # Entry point
│   └── index.css          # Global styles
├── public/                # Static assets
├── Dockerfile             # Multi-stage Docker build
├── docker-compose.yml     # Standalone deployment
├── nginx.conf            # Nginx configuration
├── vite.config.js        # Vite configuration
└── package.json          # Dependencies
```

### Adding New Features

1. **Create component:**
   ```bash
   touch src/components/NewFeature.jsx
   ```

2. **Import in App.jsx:**
   ```javascript
   import NewFeature from './components/NewFeature';
   ```

3. **Test locally:**
   ```bash
   npm run dev
   ```

4. **Build and test in Docker:**
   ```bash
   docker-compose up --build
   ```

### Build Commands

```bash
# Development server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

## Performance Metrics

The dashboard displays advanced percentile-based metrics:

- **p50 (Median)**: 50% of requests completed within this time
- **p90**: 90% of requests completed within this time
- **p95**: 95% of requests completed within this time
- **p99**: 99% of requests completed within this time

**Why percentiles matter:**
- Averages hide outliers
- p99 shows worst-case user experience
- p50 shows typical performance

## Security Considerations

**Development:**
- CORS allows all origins
- No authentication required
- Suitable for local testing only

**Production:**
- Restrict CORS origins in backend
- Add authentication to admin endpoints
- Use HTTPS/TLS
- Implement rate limiting

## License

Part of the SSE Streaming Microservice project.

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review backend logs: `cd .. && docker-compose logs backend`
3. Check dashboard logs: `docker-compose logs dashboard`
4. Verify network connectivity
