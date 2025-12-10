import React, { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { getStats } from '../api';
import { Clock } from 'lucide-react';

const MetricsChart = () => {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);

    // Polling interval in milliseconds (configurable)
    // Adjust this value to change how often metrics are fetched
    const POLLING_INTERVAL_MS = 10000; // 10 seconds

    useEffect(() => {
        const interval = setInterval(fetchStats, POLLING_INTERVAL_MS);
        fetchStats();
        return () => clearInterval(interval);
    }, []);

    const fetchStats = async () => {
        try {
            const stats = await getStats();
            // Transform stats { stageId: { count, total_time, avg_time ... } } to array
            const chartData = Object.entries(stats).map(([stage, metrics]) => ({
                stage: `Stage ${stage}`,
                avgTime: metrics.avg_time * 1000, // Convert to ms
                count: metrics.count
            }));

            // Sort by stage number
            chartData.sort((a, b) => {
                const stageA = parseFloat(a.stage.split(' ')[1]);
                const stageB = parseFloat(b.stage.split(' ')[1]);
                return stageA - stageB;
            });

            setData(chartData);
        } catch (e) {
            console.error("Failed to fetch stats", e);
        }
    };

    // Helper function to get color based on latency
    const getLatencyColor = (ms) => {
        if (ms < 100) return 'var(--success-green)';
        if (ms < 500) return 'var(--warning-yellow)';
        return 'var(--error-red)';
    };

    // Calculate metrics from data
    const avgLatency = data.length > 0 
        ? data.reduce((sum, item) => sum + item.avgTime, 0) / data.length 
        : 0;
    const totalRequests = data.reduce((sum, item) => sum + item.count, 0);
    const maxLatency = data.length > 0 ? Math.max(...data.map(item => item.avgTime)) : 0;
    const minLatency = data.length > 0 ? Math.min(...data.map(item => item.avgTime)) : 0;

    return (
        <div className="bg-bg-card border border-border rounded-xl shadow-lg">
            <div className="p-6">
                <div className="flex items-center gap-4 mb-6">
                    <div className="p-2 rounded-lg bg-purple-500/20">
                        <Clock className="text-accent-secondary" size={24} />
                    </div>
                    <h2 className="text-xl font-bold">Backend Execution Latency</h2>
                </div>

                {data.length === 0 ? (
                    <div className="text-center py-12 text-text-secondary">
                        <p>No latency data available.</p>
                        <p className="text-sm">Run a load test to see metrics.</p>
                    </div>
                ) : (
                    <>
                        {/* Metric Cards */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                            <div className="metric-card">
                                <div className="metric-label">Avg Latency</div>
                                <div className="metric-value" style={{ color: getLatencyColor(avgLatency) }}>
                                    {avgLatency.toFixed(0)}ms
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">Max Latency</div>
                                <div className="metric-value" style={{ color: getLatencyColor(maxLatency) }}>
                                    {maxLatency.toFixed(0)}ms
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">Min Latency</div>
                                <div className="metric-value" style={{ color: getLatencyColor(minLatency) }}>
                                    {minLatency.toFixed(0)}ms
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">Total Requests</div>
                                <div className="metric-value" style={{ color: 'var(--text-primary)' }}>
                                    {totalRequests}
                                </div>
                            </div>
                        </div>

                        {/* Chart */}
                        <div className="h-64 w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart
                                    data={data}
                                    layout="vertical"
                                    margin={{ top: 5, right: 30, left: 40, bottom: 5 }}
                                >
                                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                                    <XAxis type="number" stroke="#94a3b8" unit="ms" />
                                    <YAxis dataKey="stage" type="category" stroke="#f8fafc" width={80} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                                        itemStyle={{ color: '#f8fafc' }}
                                        formatter={(value) => [`${value.toFixed(2)} ms`, 'Avg Duration']}
                                    />
                                    <Bar dataKey="avgTime" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default MetricsChart;
