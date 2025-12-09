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

Write-Host "🚀 Performance Dashboard - Quick Start" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    docker info | Out-Null
    Write-Host "✅ Docker is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: Docker is not running" -ForegroundColor Red
    Write-Host "   Please start Docker Desktop and try again" -ForegroundColor Yellow
    exit 1
}

# Check if sse-network exists
try {
    docker network inspect sse-network | Out-Null
    Write-Host "✅ Backend network is available" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Warning: Backend network 'sse-network' not found" -ForegroundColor Yellow
    Write-Host "   Starting backend infrastructure first..." -ForegroundColor Yellow
    Write-Host ""
    
    # Navigate to parent directory and start backend
    Push-Location ..
    Write-Host "📦 Starting SSE backend infrastructure..." -ForegroundColor Cyan
    docker-compose up -d
    
    Write-Host ""
    Write-Host "⏳ Waiting for services to be healthy (30 seconds)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
    
    # Navigate back to dashboard
    Pop-Location
}

Write-Host ""

# Build dashboard image
Write-Host "🏗️  Building dashboard image..." -ForegroundColor Cyan
docker-compose build

Write-Host ""
Write-Host "🎯 Starting dashboard container..." -ForegroundColor Cyan
docker-compose up -d

Write-Host ""
Write-Host "⏳ Waiting for dashboard to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Check if dashboard is healthy
$status = docker-compose ps
if ($status -match "Up") {
    Write-Host ""
    Write-Host "✅ Dashboard is running!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📊 Access the dashboard at:" -ForegroundColor Cyan
    Write-Host "   http://localhost:3001" -ForegroundColor White
    Write-Host ""
    Write-Host "📝 View logs:" -ForegroundColor Cyan
    Write-Host "   docker-compose logs -f" -ForegroundColor White
    Write-Host ""
    Write-Host "🛑 Stop dashboard:" -ForegroundColor Cyan
    Write-Host "   docker-compose down" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "❌ Error: Dashboard failed to start" -ForegroundColor Red
    Write-Host "   Check logs: docker-compose logs" -ForegroundColor Yellow
    exit 1
}
