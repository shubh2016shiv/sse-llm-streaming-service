#!/usr/bin/env bash
# ============================================================================
# Performance Dashboard - Quick Start Script
# ============================================================================
#
# This script checks prerequisites and starts the dashboard
#
# Usage:
#   ./start_dashboard.sh
#
# ============================================================================

set -e

echo "🚀 Performance Dashboard - Quick Start"
echo "======================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "   Please start Docker Desktop and try again"
    exit 1
fi

echo "✅ Docker is running"

# Check if sse-network exists
if ! docker network inspect sse-network > /dev/null 2>&1; then
    echo "⚠️  Warning: Backend network 'sse-network' not found"
    echo "   Starting backend infrastructure first..."
    echo ""
    
    # Navigate to parent directory and start backend
    cd ..
    echo "📦 Starting SSE backend infrastructure..."
    docker-compose up -d
    
    echo ""
    echo "⏳ Waiting for services to be healthy (30 seconds)..."
    sleep 30
    
    # Navigate back to dashboard
    cd performance_dashboard
fi

echo "✅ Backend network is available"
echo ""

# Build dashboard image
echo "🏗️  Building dashboard image..."
docker-compose build

echo ""
echo "🎯 Starting dashboard container..."
docker-compose up -d

echo ""
echo "⏳ Waiting for dashboard to start..."
sleep 5

# Check if dashboard is healthy
if docker-compose ps | grep -q "Up"; then
    echo ""
    echo "✅ Dashboard is running!"
    echo ""
    echo "📊 Access the dashboard at:"
    echo "   http://localhost:3001"
    echo ""
    echo "📝 View logs:"
    echo "   docker-compose logs -f"
    echo ""
    echo "🛑 Stop dashboard:"
    echo "   docker-compose down"
    echo ""
else
    echo ""
    echo "❌ Error: Dashboard failed to start"
    echo "   Check logs: docker-compose logs"
    exit 1
fi
