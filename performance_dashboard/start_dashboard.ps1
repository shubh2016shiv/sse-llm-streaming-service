# ============================================================================
# Performance Dashboard - Quick Start Script (Windows)
# ============================================================================
#
# This script checks prerequisites and starts the dashboard
#
# Usage:
#   .\start_dashboard.ps1
#
# ============================================================================

Write-Host "Performance Dashboard - Quick Start" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    docker info | Out-Null
    Write-Host "Docker is running" -ForegroundColor Green
}
catch {
    Write-Host "Error: Docker is not running" -ForegroundColor Red
    Write-Host "   Please start Docker Desktop and try again" -ForegroundColor Yellow
    exit 1
}

# Check if backend is accessible
$backendRunning = $false
try {
    # Check if sse-network exists (indicates backend might be running)
    docker network inspect sse-network | Out-Null
    Write-Host "Backend network detected" -ForegroundColor Green
    
    # Try to reach the backend health endpoint
    try {
        $response = Invoke-WebRequest -Uri "http://localhost/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "Backend is accessible and healthy" -ForegroundColor Green
            $backendRunning = $true
        }
    }
    catch {
        Write-Host "Backend network exists but backend is not responding" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Backend network not found - backend is not running" -ForegroundColor Yellow
}

if (-not $backendRunning) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "BACKEND NOT RUNNING" -ForegroundColor Yellow
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "The Performance Dashboard requires the SSE backend to be running." -ForegroundColor White
    Write-Host ""
    Write-Host "To start the backend, open a new terminal and run:" -ForegroundColor Cyan
    Write-Host "   cd .." -ForegroundColor White
    Write-Host "   python start_app.py" -ForegroundColor White
    Write-Host ""
    Write-Host "This will start all necessary backend services (NGINX, FastAPI, Redis)." -ForegroundColor Gray
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    $continue = Read-Host "Do you want to start the dashboard anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        Write-Host ""
        Write-Host "Dashboard startup cancelled. Please start the backend first." -ForegroundColor Yellow
        exit 0
    }
    
    Write-Host ""
    Write-Host "Starting dashboard without backend..." -ForegroundColor Yellow
    Write-Host "Note: Dashboard will show 'Disconnected' status until backend is started." -ForegroundColor Gray
}

Write-Host ""

# Build dashboard image
Write-Host "Building dashboard image..." -ForegroundColor Cyan
docker-compose build

Write-Host ""
Write-Host "Starting dashboard container..." -ForegroundColor Cyan
docker-compose up -d

Write-Host ""
Write-Host "Waiting for dashboard to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Check if dashboard is healthy
$status = docker-compose ps
if ($status -match "Up") {
    Write-Host ""
    Write-Host "Dashboard is running!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Access the dashboard at:" -ForegroundColor Cyan
    Write-Host "   http://localhost:3001" -ForegroundColor White
    Write-Host ""
    Write-Host "View logs:" -ForegroundColor Cyan
    Write-Host "   docker-compose logs -f" -ForegroundColor White
    Write-Host ""
    Write-Host "Stop dashboard:" -ForegroundColor Cyan
    Write-Host "   docker-compose down" -ForegroundColor White
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host "Error: Dashboard failed to start" -ForegroundColor Red
    Write-Host "   Check logs: docker-compose logs" -ForegroundColor Yellow
    exit 1
}
