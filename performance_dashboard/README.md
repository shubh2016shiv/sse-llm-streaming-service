# Performance Dashboard

A modern, real-time performance monitoring dashboard for the SSE Streaming Microservice. Built with React, Vite, and Recharts to visualize execution statistics, manage configurations, and conduct load testing.

## Features

- **Backend Health Monitoring**: Real-time connection status with automatic 5-second polling
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

#### Step 1: Start the Backend

**IMPORTANT**: The dashboard requires the SSE backend to be running first.

From the **project root directory**, run:
```bash
python start_app.py
```

This will start all necessary backend services (NGINX, FastAPI instances, Redis).

Wait for the message: `"✓ All services are healthy!"`

#### Step 2: Start the Dashboard

From the **performance_dashboard directory**, run:

**Windows:**
```powershell
.\start_dashboard.ps1
```

**Linux/Mac:**
```bash
./start_dashboard.sh
```

The script will:
1. Check if Docker is running
2. Verify backend is accessible
3. Build and start the dashboard container

If the backend is not running, the script will:
- Display clear instructions to start it
- Ask if you want to continue anyway (dashboard will show "Disconnected" status)

#### Step 3: Access the Dashboard

```
http://localhost:3001
```

**Health Monitoring**: The dashboard automatically polls the backend every 5 seconds and displays connection status in the header:
- 🟢 **Connected** - Backend is healthy
- 🔴 **Disconnected** - Backend is unreachable
- 🟡 **Checking...** - Health check in progress

#### Step 4: View Logs

```bash
docker-compose logs -f
```

#### Step 5: Stop the Dashboard

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
  - VITE_API_BASE_URL=http://sse-nginx/api/v1

  # Option 2: Direct to specific app instance
  - VITE_API_BASE_URL=http://sse-app-1:8000/api/v1

  # Option 3: Use host machine
  - VITE_API_BASE_URL=http://host.docker.internal:8000/api/v1
```

### Adjusting Polling Intervals

The dashboard polls the backend at regular intervals. You can adjust these intervals by editing the source files:

#### Backend Health Check Polling

**File**: `src/components/BackendStatusIndicator.jsx`  
**Default**: 5 seconds  
**Line**: ~30

```javascript
const POLLING_INTERVAL_MS = 5000; // 5 seconds
```

Change this value to adjust how often the dashboard checks backend connectivity.

#### Metrics Chart Polling

**File**: `src/components/MetricsChart.jsx`  
**Default**: 10 seconds  
**Line**: ~12

```javascript
const POLLING_INTERVAL_MS = 10000; // 10 seconds
```

Change this value to adjust how often execution statistics are fetched.

> [!NOTE]
> After changing polling intervals, you must rebuild the dashboard container:
> ```bash
> docker-compose down
> docker-compose up -d --build
> ```

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
| `/health` | GET | Backend health check (polled every 5s) |
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

### Dashboard can't connect to backend

**Symptoms:**
- Status indicator shows "Disconnected" (red)
- API requests fail in browser console
- "Failed to fetch" errors

**Solutions:**

1. **Start the backend:**
   ```bash
   cd ..
   python start_app.py
   ```
   Dashboard will auto-reconnect within 5 seconds.

2. **Verify backend health manually:**
   ```bash
   curl http://localhost/health
   ```

3. **Check backend status:**
   ```bash
   cd ..
   docker-compose ps
   ```

4. **Test connectivity from dashboard container:**
   ```bash
   docker exec performance-dashboard wget -O- http://sse-nginx/health
   ```

### Backend not running

**Symptoms:**
- Dashboard shows "Backend: Disconnected" status
- Startup script displays "BACKEND NOT RUNNING" message
- Network errors in browser console

**Solution:**
Start the backend from the project root:
```bash
cd ..
python start_app.py
```

The dashboard will automatically detect the connection within 5 seconds.

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
│   ├── components/              # React components
│   │   ├── BackendStatusIndicator.jsx  # Real-time health monitor
│   │   ├── ConfigurationPanel.jsx
│   │   ├── LoadTester.jsx
│   │   └── MetricsChart.jsx
│   ├── api.js                  # API client + health checks
│   ├── App.jsx                 # Main app component
│   ├── main.jsx                # Entry point
│   └── index.css               # Global styles
├── public/                     # Static assets
├── Dockerfile                  # Multi-stage Docker build
├── docker-compose.yml          # Standalone deployment
├── nginx.conf                  # Nginx configuration
├── start_dashboard.ps1         # Windows startup script
├── start_dashboard.sh          # Linux/Mac startup script
├── vite.config.js              # Vite configuration
└── package.json                # Dependencies
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
