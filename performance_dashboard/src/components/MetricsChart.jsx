import React, { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { getStats } from '../api';
import { Clock } from 'lucide-react';

const MetricsChart = () => {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const interval = setInterval(fetchStats, 2000);
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

    return (
        <div className="card glass-card">
            <div className="flex items-center gap-4 mb-6">
                <Clock className="text-accent-secondary" size={24} />
                <h2 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400">
                    Backend Execution Latency
                </h2>
            </div>

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
                            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                            itemStyle={{ color: '#f8fafc' }}
                            formatter={(value) => [`${value.toFixed(2)} ms`, 'Avg Duration']}
                        />
                        <Bar dataKey="avgTime" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default MetricsChart;
