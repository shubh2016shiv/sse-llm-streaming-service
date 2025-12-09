import axios from 'axios';

// API Base URL - configurable via environment variable
// Development: http://localhost:8000/api/v1 (default - includes API prefix)
// Docker: Set via VITE_API_BASE_URL in docker-compose.yml
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

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
