import React, { useEffect, useState } from 'react';
import { Activity, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { checkBackendHealth } from '../api';

/**
 * Backend Status Indicator Component
 * 
 * Displays real-time backend connectivity status with automatic polling.
 * 
 * Features:
 * - Auto-polls backend health every 5 seconds
 * - Visual status indicator (Connected/Disconnected/Checking)
 * - Color-coded feedback (green/red/yellow)
 * - Last successful check timestamp
 * - Manual retry button
 * 
 * Enterprise Pattern: Separation of Concerns
 * This component handles ONLY health monitoring, not backend orchestration.
 */
const BackendStatusIndicator = () => {
    const [status, setStatus] = useState({
        healthy: null, // null = checking, true = connected, false = disconnected
        lastCheck: null,
        error: null,
    });
    const [isManualChecking, setIsManualChecking] = useState(false);

    // Polling interval in milliseconds (configurable)
    // Adjust this value to change how often backend health is checked
    const POLLING_INTERVAL_MS = 5000; // 5 seconds

    /**
     * Poll Backend Health
     * Runs every 5 seconds in a separate "thread" (setInterval)
     */
    const pollHealth = async () => {
        const result = await checkBackendHealth();
        setStatus({
            healthy: result.healthy,
            lastCheck: result.timestamp,
            error: result.error,
        });
    };

    // Auto-poll on mount and every 5 seconds
    useEffect(() => {
        // Initial check
        pollHealth();

        // Set up polling interval (5 seconds)
        const intervalId = setInterval(() => {
            pollHealth();
        }, POLLING_INTERVAL_MS);

        // Cleanup on unmount
        return () => clearInterval(intervalId);
    }, []);

    /**
     * Manual Retry Handler
     * Allows user to force a health check
     */
    const handleManualRetry = async () => {
        setIsManualChecking(true);
        await pollHealth();
        setTimeout(() => setIsManualChecking(false), 500);
    };

    // Determine visual state
    const getStatusConfig = () => {
        if (status.healthy === null) {
            return {
                icon: Activity,
                text: 'Checking...',
                color: 'text-yellow-400',
                bgColor: 'bg-yellow-500/10',
                borderColor: 'border-yellow-500/30',
            };
        } else if (status.healthy) {
            return {
                icon: CheckCircle,
                text: 'Connected',
                color: 'text-green-400',
                bgColor: 'bg-green-500/10',
                borderColor: 'border-green-500/30',
            };
        } else {
            return {
                icon: XCircle,
                text: 'Disconnected',
                color: 'text-red-400',
                bgColor: 'bg-red-500/10',
                borderColor: 'border-red-500/30',
            };
        }
    };

    const statusConfig = getStatusConfig();
    const StatusIcon = statusConfig.icon;

    // Format timestamp
    const formatLastCheck = () => {
        if (!status.lastCheck) return 'Never';
        const date = new Date(status.lastCheck);
        return date.toLocaleTimeString();
    };

    return (
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg border text-sm ${statusConfig.bgColor} ${statusConfig.borderColor}`}>
            {/* Status Indicator Dot */}
            {status.healthy && (
                <div 
                    className="rounded-full animate-pulse"
                    style={{
                        width: '8px',
                        height: '8px',
                        background: 'var(--success-green)',
                        boxShadow: '0 0 8px var(--success-green)'
                    }}
                    aria-hidden="true"
                ></div>
            )}
            
            {/* Status Icon */}
            <StatusIcon
                className={`${statusConfig.color} ${status.healthy === null ? 'animate-pulse' : ''}`}
                size={18}
                aria-hidden="true"
            />

            {/* Status Text */}
            <div className="flex flex-col">
                <span className={`font-semibold ${statusConfig.color}`}>
                    Backend: {statusConfig.text}
                </span>
                <span className="text-xs text-text-muted">
                    Last check: {formatLastCheck()}
                </span>
            </div>

            {/* Manual Retry Button */}
            {!status.healthy && (
                <button
                    onClick={handleManualRetry}
                    disabled={isManualChecking}
                    className="ml-2 p-1.5 rounded-md hover:bg-white/10 transition-colors"
                    title="Retry connection"
                >
                    <RefreshCw
                        size={14}
                        className={`text-text-secondary ${isManualChecking ? 'animate-spin' : ''}`}
                    />
                </button>
            )}
        </div>
    );
};

export default BackendStatusIndicator;
