import React, { useState, useRef, useEffect } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { Play, Square, Activity, Users, Clock, AlertCircle, TrendingUp } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

const API_BASE_URL = 'http://localhost:8000';

const LoadTester = () => {
    const [running, setRunning] = useState(false);
    const [concurrency, setConcurrency] = useState(10);
    const [totalRequests, setTotalRequests] = useState(50);

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
                    query: "Write a short poem about performance testing.",
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

    return (
        <div className="card glass-card">
            <div className="flex items-center gap-4 mb-6">
                <Activity className="text-accent-secondary" size={24} />
                <h2 className="text-xl font-bold">Load Tester</h2>
            </div>

            <div className="grid grid-cols-2 gap-6 mb-6">
                <div>
                    <label className="block text-sm text-gray-400 mb-2">Concurrency (Simulated Users)</label>
                    <div className="flex items-center gap-4">
                        <Users size={18} className="text-gray-500" />
                        <input
                            type="range"
                            min="1"
                            max="50"
                            value={concurrency}
                            onChange={(e) => setConcurrency(parseInt(e.target.value))}
                            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
                            disabled={running}
                        />
                        <span className="text-xl font-mono font-bold w-8">{concurrency}</span>
                    </div>
                </div>
                <div>
                    <label className="block text-sm text-gray-400 mb-2">Total Requests</label>
                    <div className="flex items-center gap-4">
                        <input
                            type="number"
                            value={totalRequests}
                            onChange={(e) => setTotalRequests(parseInt(e.target.value))}
                            className="input font-mono"
                            disabled={running}
                        />
                    </div>
                </div>
            </div>

            <div className="flex gap-4 mb-8">
                {!running ? (
                    <button onClick={startLoadTest} className="btn btn-primary w-full text-lg">
                        <Play fill="currentColor" size={20} /> Start Load Test
                    </button>
                ) : (
                    <button onClick={stopLoadTest} className="btn bg-danger text-white w-full text-lg hover:bg-red-600">
                        <Square fill="currentColor" size={20} /> Stop Test
                    </button>
                )}
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-bg-dark p-4 rounded-xl border border-border">
                    <div className="text-sm text-gray-400 mb-1">Active</div>
                    <div className="text-2xl font-bold text-blue-400">{stats.active}</div>
                </div>
                <div className="bg-bg-dark p-4 rounded-xl border border-border">
                    <div className="text-sm text-gray-400 mb-1">Completed</div>
                    <div className="text-2xl font-bold text-green-400">{stats.completed}</div>
                </div>
                <div className="bg-bg-dark p-4 rounded-xl border border-border">
                    <div className="text-sm text-gray-400 mb-1">Failed</div>
                    <div className="text-2xl font-bold text-red-400">{stats.failed}</div>
                </div>
                <div className="bg-bg-dark p-4 rounded-xl border border-border">
                    <div className="text-sm text-gray-400 mb-1">Total Tokens</div>
                    <div className="text-2xl font-bold text-yellow-400">{stats.totalTokens}</div>
                </div>
            </div>

            {/* Chart */}
            <div className="h-48 w-full bg-bg-dark rounded-xl border border-border p-2 mb-6">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                        <XAxis dataKey="time" hide />
                        <YAxis hide domain={[0, 'auto']} />
                        <Tooltip
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                            itemStyle={{ color: '#f8fafc' }}
                        />
                        <Line type="monotone" dataKey="active" stroke="#3b82f6" strokeWidth={2} dot={false} name="Active" />
                        <Line type="monotone" dataKey="completed" stroke="#10b981" strokeWidth={2} dot={false} name="Completed" />
                    </LineChart>
                </ResponsiveContainer>
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
                                <td className="text-green-400">{percentiles.p50.toFixed(0)}</td>
                                <td className="text-sm text-gray-400">50% of requests completed faster</td>
                            </tr>
                            <tr>
                                <td>p90</td>
                                <td className="text-blue-400">{percentiles.p90.toFixed(0)}</td>
                                <td className="text-sm text-gray-400">90% of requests completed faster</td>
                            </tr>
                            <tr>
                                <td>p95</td>
                                <td className="text-yellow-400">{percentiles.p95.toFixed(0)}</td>
                                <td className="text-sm text-gray-400">95% of requests completed faster</td>
                            </tr>
                            <tr>
                                <td>p99</td>
                                <td className="text-red-400">{percentiles.p99.toFixed(0)}</td>
                                <td className="text-sm text-gray-400">99% of requests completed faster</td>
                            </tr>
                            <tr>
                                <td>Total Requests</td>
                                <td>{latencies.length}</td>
                                <td className="text-sm text-gray-400">Completed successfully</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default LoadTester;
