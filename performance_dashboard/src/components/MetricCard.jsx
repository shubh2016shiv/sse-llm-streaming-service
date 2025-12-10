import React from 'react';
import { Clock, TrendingUp, Zap, Activity } from 'lucide-react';

const MetricCard = ({ label, value, unit = 'ms', threshold = null }) => {
    // Determine color based on threshold
    const getThresholdColor = () => {
        if (!threshold || !value) return 'text-blue-400';

        if (threshold === 'low') {
            return value < 100 ? 'threshold-low' : value < 500 ? 'threshold-medium' : 'threshold-high';
        } else if (threshold === 'medium') {
            return value < 200 ? 'threshold-low' : value < 800 ? 'threshold-medium' : 'threshold-high';
        } else if (threshold === 'high') {
            return value < 500 ? 'threshold-low' : value < 1000 ? 'threshold-medium' : 'threshold-high';
        }
        return 'text-blue-400';
    };

    const colorClass = getThresholdColor();

    return (
        <div className="metric-card">
            <div className="metric-label">{label}</div>
            <div className={`metric-value ${colorClass}`}>
                {value ? value.toFixed(0) : '--'}
                <span className="text-sm ml-1 text-gray-600">{unit}</span>
            </div>
        </div>
    );
};

export default MetricCard;
