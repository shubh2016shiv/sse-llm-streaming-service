import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000'; // Adjust if backend runs elsewhere

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
