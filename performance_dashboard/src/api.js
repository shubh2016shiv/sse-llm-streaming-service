import axios from 'axios';

// ===========================================================================
// 🔄 LOAD BALANCER INTEGRATION - CRITICAL ARCHITECTURE
// ===========================================================================
// 
// WHY LOAD BALANCING MATTERS:
// ---------------------------
// This application uses NGINX as a load balancer to distribute requests
// across multiple FastAPI backend instances. This provides:
// - HIGH AVAILABILITY: If one instance fails, others continue serving
// - HORIZONTAL SCALING: Add more instances to handle increased load
// - DISTRIBUTED CONNECTION POOL: Each instance has separate limits
// 
// ARCHITECTURE OVERVIEW:
// ----------------------
//   Performance Dashboard (UI) → NGINX Load Balancer → Backend Instances
//   http://localhost:3001      → https://localhost   → app-1:8000 (33%)
//                                                     → app-2:8000 (33%)
//                                                     → app-3:8000 (34%)
//
// ===========================================================================
// ⚙️ API BASE URL CONFIGURATION
// ===========================================================================
//
// PRODUCTION/DOCKER SETUP (RECOMMENDED):
// ---------------------------------------
// URL: https://localhost/api/v1
// 
// Flow: UI → NGINX (port 443) → Load Balanced to 3 FastAPI instances
// 
// Benefits:
// ✅ Requests distributed across 3 instances
// ✅ SSL/TLS encryption via NGINX
// ✅ Connection pool capacity: 3 connections per user × 3 instances = 9 total
// ✅ True horizontal scaling
// ✅ Production-like environment
//
// How to run:
// 1. python infrastructure/manage.py start --all
// 2. Access dashboard: http://localhost:3001
// 3. All API calls automatically routed through NGINX
//
// DEVELOPMENT SETUP (LOCAL DEBUGGING):
// -------------------------------------
// URL: http://localhost:8000/api/v1
//
// Flow: UI → Direct to single FastAPI instance (bypasses NGINX)
//
// Benefits:
// ✅ Can use debugger on local instance
// ✅ Faster iteration (no Docker restart needed)
// ✅ Simpler logging (direct console output)
//
// Limitations:
// ❌ NO load balancing (single instance only)
// ❌ NO SSL encryption
// ❌ Connection pool capacity limited to 3 per user
// ❌ Not representative of production
//
// How to run:
// 1. python start_app.py
// 2. Update this URL to: 'http://localhost:8000/api/v1'
// 3. Restart dashboard
//
// ===========================================================================
// 🎯 CURRENT CONFIGURATION
// ===========================================================================
//
// The URL below determines which mode the dashboard operates in:
// - https://localhost/api/v1      → Production mode (load balanced)
// - http://localhost:8000/api/v1  → Development mode (single instance)
//
// Environment Variable Override:
// Set VITE_API_BASE_URL to override default (useful for Docker deployment)
//
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://localhost/api/v1';

export const api = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export const getStats = async () => {
    const response = await api.get('/admin/execution-stats');
    return response.data;
};

export const getConfig = async () => {
    const response = await api.get('/admin/config');
    return response.data;
};

export const updateConfig = async (config) => {
    const response = await api.post('/admin/config', config);
    return response.data;
};

export const runLoadTest = async ({ concurrency, provider, prompt }) => {
    // This function will need to manage multiple parallel requests from the client side
    // or call a backend load test endpoint if one existed (but we are building a client-side load tester)
    // We will implement the logic in the component, but here we can define the single stream request.

    // Use API_BASE_URL to ensure /api/v1 prefix is included
    const response = await fetch(`${API_BASE_URL}/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            query: prompt,
            provider: provider,
            stream: true
        })
    });
    return response;
};

/**
 * Check Backend Health Status
 * 
 * Polls the backend /health endpoint to verify connectivity.
 * Used by the dashboard to monitor backend availability in real-time.
 * 
 * @returns {Promise<{healthy: boolean, timestamp: string, error?: string}>}
 */
export const checkBackendHealth = async () => {
    const timestamp = new Date().toISOString();

    try {
        const response = await api.get('/health', {
            timeout: 3000, // 3 second timeout
        });

        return {
            healthy: response.status === 200,
            timestamp,
            data: response.data,
        };
    } catch (error) {
        // Network error or backend not reachable
        return {
            healthy: false,
            timestamp,
            error: error.code === 'ECONNABORTED'
                ? 'Request timeout'
                : error.message || 'Backend not reachable',
        };
    }
};
