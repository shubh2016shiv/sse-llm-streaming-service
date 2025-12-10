import React, { useState, useRef, useEffect } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { Play, Square, Activity, Users, TrendingUp } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

// Import API_BASE_URL from api.js to ensure consistency
// This will use the same base URL as other API calls (includes /api/v1 prefix)
import { api } from '../api';

const API_BASE_URL = api.defaults.baseURL;

const LoadTester = () => {
    const [running, setRunning] = useState(false);
    const [concurrency, setConcurrency] = useState(10);
    const [totalRequests, setTotalRequests] = useState(50);

    // User-configurable prompt and provider
    const [prompt, setPrompt] = useState("Write a short poem about performance testing.");
    const [provider, setProvider] = useState("fake");
    const [model, setModel] = useState("gpt-3.5-turbo");

    // Real-time metrics
    const [stats, setStats] = useState({
        active: 0,
        completed: 0,
        failed: 0,
        totalTokens: 0,
    });

    // Latency tracking for percentiles
    const [latencies, setLatencies] = useState([]);
    const [percentiles, setPercentiles] = useState({ p50: 0, p90: 0, p95: 0, p99: 0 });

    // Time series data for chart
    const [chartData, setChartData] = useState([]);

    const abortControllerRef = useRef(null);
    const startTimeRef = useRef(null);

    useEffect(() => {
        let interval;
        if (running) {
            interval = setInterval(() => {
                setChartData(prev => {
                    const now = (Date.now() - startTimeRef.current) / 1000;
                    const newData = [...prev, {
                        time: now.toFixed(1),
                        active: stats.active,
                        completed: stats.completed,
                    }];
                    return newData.slice(-30);
                });
            }, 1000);
        }
        return () => clearInterval(interval);
    }, [running, stats]);

    const calculatePercentiles = (latencyArray) => {
        if (latencyArray.length === 0) return { p50: 0, p90: 0, p95: 0, p99: 0 };

        const sorted = [...latencyArray].sort((a, b) => a - b);
        const getPercentile = (p) => {
            const index = Math.ceil((p / 100) * sorted.length) - 1;
            return sorted[Math.max(0, index)];
        };

        return {
            p50: getPercentile(50),
            p90: getPercentile(90),
            p95: getPercentile(95),
            p99: getPercentile(99),
        };
    };

    const runSingleRequest = async (id) => {
        const start = Date.now();
        let ttft = 0;

        try {
            setStats(prev => ({ ...prev, active: prev.active + 1 }));

            await fetchEventSource(`${API_BASE_URL}/stream`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: prompt,  // Use user-provided prompt
                    model: model,   // Use selected model
                    provider: provider,  // Use selected provider
                    stream: true
                }),
                signal: abortControllerRef.current.signal,
                onopen(res) {
                    if (res.ok && res.status === 200) {
                        ttft = Date.now() - start;
                    } else if (res.status >= 400 && res.status < 500 && res.status !== 429) {
                        throw new Error("Client error");
                    }
                },
                onmessage(ev) {
                    if (ev.data === '[DONE]') return;
                    try {
                        setStats(prev => ({ ...prev, totalTokens: prev.totalTokens + 1 }));
                    } catch (e) { }
                },
                onerror(err) {
                    throw err;
                }
            });

            const totalLatency = Date.now() - start;
            setLatencies(prev => [...prev, totalLatency]);
            setStats(prev => ({ ...prev, active: prev.active - 1, completed: prev.completed + 1 }));
        } catch (err) {
            setStats(prev => ({ ...prev, active: prev.active - 1, failed: prev.failed + 1 }));
        }
    };

    const startLoadTest = async () => {
        if (running) return;

        setRunning(true);
        setStats({ active: 0, completed: 0, failed: 0, totalTokens: 0 });
        setLatencies([]);
        setChartData([]);
        abortControllerRef.current = new AbortController();
        startTimeRef.current = Date.now();

        const workers = [];
        for (let i = 0; i < concurrency; i++) workers.push(i);

        let tasksRemaining = totalRequests;

        const worker = async () => {
            while (tasksRemaining > 0 && !abortControllerRef.current.signal.aborted) {
                tasksRemaining--;
                await runSingleRequest();
            }
        };

        await Promise.all(workers.map(worker));

        setRunning(false);
    };

    const stopLoadTest = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        setRunning(false);
    };

    // Calculate percentiles when test completes
    useEffect(() => {
        if (!running && latencies.length > 0) {
            setPercentiles(calculatePercentiles(latencies));
        }
    }, [running, latencies]);

    // Calculate progress percentage
    const progressPercentage = totalRequests > 0 
        ? ((stats.completed + stats.failed) / totalRequests) * 100 
        : 0;

    return (
        <div className="bg-bg-card border border-border rounded-xl shadow-lg">
            <div className="p-6">
                <div className="flex items-center gap-4 mb-6">
                    <div className="p-2 rounded-lg bg-purple-500/20">
                        <Activity className="text-accent-secondary" size={24} />
                    </div>
                    <h2 className="text-xl font-bold">Load Tester</h2>
                </div>

                {/* Form Controls */}
                <div className="space-y-6">
                    {/* Prompt Configuration */}
                    <div>
                        <label htmlFor="prompt-text" className="block text-sm font-medium text-text-secondary mb-2">Prompt Text</label>
                        <textarea
                            id="prompt-text"
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            className="w-full p-3 bg-bg-dark border border-border rounded-lg text-text-primary resize-none focus:outline-none focus:ring-accent-primary font-mono"
                            rows="3"
                            placeholder="Enter your prompt here..."
                            disabled={running}
                        />
                    </div>

                    {/* Provider and Model Selection */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                        <div>
                            <label htmlFor="provider-select" className="block text-sm font-medium text-text-secondary mb-2">Provider</label>
                            <select
                                id="provider-select"
                                value={provider}
                                onChange={(e) => setProvider(e.target.value)}
                                className="w-full p-3 bg-bg-dark border border-border rounded-lg text-text-primary focus:outline-none focus:ring-accent-primary"
                                disabled={running}
                            >
                                <option value="fake">Fake LLM (Testing)</option>
                                <option value="openai">OpenAI</option>
                                <option value="anthropic">Anthropic</option>
                            </select>
                        </div>
                        <div>
                            <label htmlFor="model-input" className="block text-sm font-medium text-text-secondary mb-2">Model</label>
                            <input
                                id="model-input"
                                type="text"
                                value={model}
                                onChange={(e) => setModel(e.target.value)}
                                className="w-full p-3 bg-bg-dark border border-border rounded-lg text-text-primary focus:outline-none focus:ring-accent-primary"
                                placeholder="e.g., gpt-3.5-turbo"
                                disabled={running}
                            />
                        </div>
                    </div>

                    {/* Sliders and Inputs */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <label htmlFor="concurrency-slider" className="text-sm font-medium text-text-secondary">Concurrency</label>
                                <span className="text-lg font-mono font-bold text-accent-primary">{concurrency}</span>
                            </div>
                            <div className="flex items-center gap-4">
                                <Users size={18} className="text-text-muted" />
                                <input
                                    id="concurrency-slider"
                                    type="range"
                                    min="1"
                                    max="50"
                                    value={concurrency}
                                    onChange={(e) => setConcurrency(parseInt(e.target.value))}
                                    className="w-full h-2 bg-bg-tertiary rounded-lg appearance-none cursor-pointer"
                                    disabled={running}
                                />
                            </div>
                        </div>
                        <div>
                            <label htmlFor="total-requests-input" className="block text-sm font-medium text-text-secondary mb-2">Total Requests</label>
                            <input
                                id="total-requests-input"
                                type="number"
                                value={totalRequests}
                                onChange={(e) => setTotalRequests(parseInt(e.target.value))}
                                className="w-full p-3 bg-bg-dark border border-border rounded-lg text-text-primary font-mono focus:outline-none focus:ring-accent-primary"
                                disabled={running}
                            />
                        </div>
                    </div>

                    {/* Progress Bar */}
                    {running && (
                        <div className="mb-6">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>Progress</span>
                                <span className="text-sm font-semibold" style={{ color: 'var(--accent-primary)' }}>
                                    {Math.round(progressPercentage)}%
                                </span>
                            </div>
                            <div className="progress-bar">
                                <div 
                                    className="progress-bar-fill" 
                                    style={{ width: `${progressPercentage}%` }}
                                ></div>
                            </div>
                        </div>
                    )}

                    {/* Action Buttons */}
                    <div className="pt-6">
                        {!running ? (
                            <button
                                onClick={startLoadTest}
                                className="w-full flex items-center justify-center gap-3 py-3 px-6 text-lg font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                                style={{ background: 'linear-gradient(135deg, var(--primary-blue), var(--primary-purple))' }}
                            >
                                <Play size={20} /> Start Load Test
                            </button>
                        ) : (
                            <button
                                onClick={stopLoadTest}
                                className="w-full flex items-center justify-center gap-3 py-3 px-6 text-lg font-semibold text-white bg-danger rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                            >
                                <Square size={20} /> Stop Test
                            </button>
                        )}
                    </div>

                    {/* Metrics Grid */}
                    <div className="pt-8">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                                <div className="text-sm text-blue-300">Active</div>
                                <div className="text-2xl font-bold text-blue-400">{stats.active}</div>
                            </div>
                            <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-lg">
                                <div className="text-sm text-green-300">Completed</div>
                                <div className="text-2xl font-bold text-green-400">{stats.completed}</div>
                            </div>
                            <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
                                <div className="text-sm text-red-300">Failed</div>
                                <div className="text-2xl font-bold text-red-400">{stats.failed}</div>
                            </div>
                            <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                                <div className="text-sm text-yellow-300">Total Tokens</div>
                                <div className="text-2xl font-bold text-yellow-400">{stats.totalTokens}</div>
                            </div>
                        </div>
                    </div>

                    {/* Chart */}
                    <div className="h-48 w-full rounded-xl border p-2 mb-6" style={{ 
                        background: 'var(--bg-dark)', 
                        borderColor: 'var(--border)',
                        borderRadius: '12px'
                    }}>
                        {chartData.length === 0 ? (
                            <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
                                Chart will appear when test starts
                            </div>
                        ) : (
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={chartData}>
                                    <XAxis dataKey="time" hide />
                                    <YAxis hide domain={[0, 'auto']} />
                                    <Tooltip
                                        contentStyle={{ 
                                            backgroundColor: 'var(--bg-card)', 
                                            border: '1px solid var(--border)',
                                            borderRadius: '8px'
                                        }}
                                        itemStyle={{ color: 'var(--text-primary)' }}
                                    />
                                    <Line type="monotone" dataKey="active" stroke="#3b82f6" strokeWidth={2} dot={false} name="Active" />
                                    <Line type="monotone" dataKey="completed" stroke="#10b981" strokeWidth={2} dot={false} name="Completed" />
                                </LineChart>
                            </ResponsiveContainer>
                        )}
                    </div>

                    {/* Percentile Results Table */}
                    {!running && latencies.length > 0 && (
                        <div className="mt-6">
                            <div className="flex items-center gap-3 mb-4">
                                <TrendingUp className="text-purple-400" size={20} />
                                <h3 className="text-lg font-bold">Latency Percentiles</h3>
                            </div>
                            <table className="results-table">
                                <thead>
                                    <tr>
                                        <th>Metric</th>
                                        <th>Value (ms)</th>
                                        <th>Description</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td>p50 (Median)</td>
                                        <td className="text-green-400" aria-label={`p50 latency: ${percentiles.p50.toFixed(0)} milliseconds`}>{percentiles.p50.toFixed(0)}</td>
                                        <td className="text-sm text-gray-400">50% of requests completed faster</td>
                                    </tr>
                                    <tr>
                                        <td>p90</td>
                                        <td className="text-blue-400" aria-label={`p90 latency: ${percentiles.p90.toFixed(0)} milliseconds`}>{percentiles.p90.toFixed(0)}</td>
                                        <td className="text-sm text-gray-400">90% of requests completed faster</td>
                                    </tr>
                                    <tr>
                                        <td>p95</td>
                                        <td className="text-yellow-400" aria-label={`p95 latency: ${percentiles.p95.toFixed(0)} milliseconds`}>{percentiles.p95.toFixed(0)}</td>
                                        <td className="text-sm text-gray-400">95% of requests completed faster</td>
                                    </tr>
                                    <tr>
                                        <td>p99</td>
                                        <td className="text-red-400" aria-label={`p99 latency: ${percentiles.p99.toFixed(0)} milliseconds`}>{percentiles.p99.toFixed(0)}</td>
                                        <td className="text-sm text-gray-400">99% of requests completed faster</td>
                                    </tr>
                                    <tr>
                                        <td>Total Requests</td>
                                        <td aria-label={`Total requests: ${latencies.length}`}>{latencies.length}</td>
                                        <td className="text-sm text-gray-400">Completed successfully</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default LoadTester;
