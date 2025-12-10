import React, { useEffect, useState } from 'react';
import { Activity, Database, Server, Clock, BarChart2, Zap, Layers } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';
import { getStreamingMetrics } from '../api';

const StreamingMetrics = () => {
    const [metrics, setMetrics] = useState(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState(new Date());

    useEffect(() => {
        fetchMetrics();
        const interval = setInterval(fetchMetrics, 3000); // Faster refresh for "live" feel
        return () => clearInterval(interval);
    }, []);

    const fetchMetrics = async () => {
        try {
            const data = await getStreamingMetrics();
            setMetrics(data);
            setLastUpdated(new Date());
            setLoading(false);
        } catch (err) {
            console.error("Failed to fetch streaming metrics", err);
            // Don't set loading false on error to keep showing old data if valid
        }
    };

    if (loading && !metrics) return <div className="p-8 text-center text-gray-500 animate-pulse">Initializing telemetry...</div>;
    if (!metrics) return null;

    // --- Transforms for Visualization ---

    // 1. Connection Pool Health
    const poolUtil = metrics?.connection_pool?.utilization_percent || 0;
    const poolColor = poolUtil > 90 ? '#ef4444' : poolUtil > 70 ? '#eab308' : '#10b981';

    // 2. Stage Breakdown Data (Top Level)
    const stageData = [
        { name: 'Validation', value: metrics.stages['1']?.avg_duration_ms || 0 },
        { name: 'Cache', value: metrics.stages['2']?.avg_duration_ms || 0 },
        { name: 'Rate Limit', value: metrics.stages['3']?.avg_duration_ms || 0 },
        { name: 'Provider', value: metrics.stages['4']?.avg_duration_ms || 0 },
        { name: 'Streaming', value: metrics.stages['5']?.avg_duration_ms || 0 },
    ];

    // Filter out stages with 0 duration to keep chart clean, but keep at least one if all empty
    const activeStages = stageData.filter(s => s.value > 0);
    const chartData = activeStages.length > 0 ? activeStages : [{ name: 'Idle', value: 0 }];

    // 3. Cache Stats
    const l1HitRate = (metrics.cache?.l1?.hit_rate || 0) * 100;

    return (
        <div className="card glass-card card-accent-purple card-hover card-glow-purple relative overflow-hidden">
            <div className="absolute top-0 left-0 w-1 h-full bg-gradient-to-b from-blue-500 via-purple-500 to-pink-500"></div>

            <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-pink-500/20 rounded-lg">
                        <BarChart2 className="text-pink-400" size={24} />
                    </div>
                    <div>
                        <h2 className="text-xl font-bold text-white">Live Telemetry</h2>
                        <div className="flex items-center gap-2 text-xs text-gray-400">
                            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                            Updated: {lastUpdated.toLocaleTimeString()}
                        </div>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

                {/* 1. Infrastructure Health */}
                <div className="space-y-6">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2">
                        <Server size={14} /> Infrastructure
                    </h3>

                    {/* Connection Pool */}
                    <div className="bg-bg-dark/50 p-4 rounded-xl border border-white/5">
                        <div className="flex justify-between mb-2">
                            <span className="text-sm font-medium text-gray-300">Connection Pool</span>
                            <span className="text-sm font-bold" style={{ color: poolColor }}>{poolUtil}%</span>
                        </div>
                        <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
                            <div
                                className="h-full transition-all duration-500 ease-out"
                                style={{ width: `${poolUtil}%`, backgroundColor: poolColor }}
                            ></div>
                        </div>
                        <div className="mt-2 text-xs text-gray-500 flex justify-between">
                            <span>{metrics.connection_pool?.active || 0} active</span>
                            <span>{metrics.connection_pool?.max || 100} capacity</span>
                        </div>
                    </div>

                    {/* Cache Performance */}
                    <div className="bg-bg-dark/50 p-4 rounded-xl border border-white/5">
                        <div className="flex justify-between mb-2">
                            <span className="text-sm font-medium text-gray-300">L1 Cache Hit Rate</span>
                            <span className="text-sm font-bold text-cyan-400">{l1HitRate.toFixed(1)}%</span>
                        </div>
                        <div className="flex items-end gap-1 h-8 mb-1">
                            {[...Array(10)].map((_, i) => (
                                <div
                                    key={i}
                                    className={`flex-1 rounded-sm transition-all ${i < (l1HitRate / 10) ? 'bg-cyan-500' : 'bg-gray-800'}`}
                                    style={{ height: i < (l1HitRate / 10) ? '100%' : '20%' }}
                                ></div>
                            ))}
                        </div>
                        <div className="text-xs text-gray-500">
                            {metrics.cache?.l1?.size || 0} items cached
                        </div>
                    </div>
                </div>

                {/* 2. Latency Breakdown Chart */}
                <div className="md:col-span-2 bg-bg-dark/30 p-4 rounded-xl border border-white/5 flex flex-col">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2 mb-4">
                        <Layers size={14} /> Latency Breakdown (Avg ms)
                    </h3>
                    <div className="flex-1 w-full min-h-[160px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                                <XAxis type="number" stroke="#666" fontSize={12} tickFormatter={(val) => `${val}ms`} />
                                <YAxis dataKey="name" type="category" stroke="#999" fontSize={12} width={80} />
                                <RechartsTooltip
                                    cursor={{ fill: '#ffffff10' }}
                                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                                />
                                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                                    {chartData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={['#818cf8', '#34d399', '#f472b6', '#fbbf24', '#60a5fa'][index % 5]} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* 3. Detailed Percentiles Grid */}
            <div className="mt-6 pt-6 border-t border-gray-800">
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-2 mb-4">
                    <Clock size={14} /> Stage Performance (p99)
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    {Object.entries(metrics.stages).map(([id, stage]) => {
                        if (['2.1', '2.2'].includes(id)) return null; // Skip sub-stages for cleanliness
                        const nameMap = {
                            '1': 'Valid',
                            '2': 'Cache',
                            '3': 'RateLimit',
                            '4': 'Context',
                            '5': 'Generate',
                            '6': 'Cleanup'
                        };
                        return (
                            <div key={id} className="bg-gray-900/40 p-3 rounded-lg border border-gray-800 hover:border-gray-700 transition-colors">
                                <div className="text-xs text-gray-500 mb-1">{nameMap[id] || id}</div>
                                <div className="text-lg font-mono font-bold text-gray-200">
                                    {stage.p99_duration_ms}<span className="text-xs font-normal text-gray-600 ml-1">ms</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default StreamingMetrics;
