import React, { useEffect, useState } from 'react';
import { Settings, Save, RefreshCw, Server, Zap, Database } from 'lucide-react';
import { getConfig, updateConfig } from '../api';

const ConfigurationPanel = () => {
    const [config, setConfig] = useState({
        USE_FAKE_LLM: true,
        ENABLE_CACHING: true,
        QUEUE_TYPE: 'redis',
    });
    const [loading, setLoading] = useState(false);
    const [status, setStatus] = useState('');

    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = async () => {
        setLoading(true);
        try {
            const data = await getConfig();
            setConfig(data);
        } catch (err) {
            console.error("Failed to load config", err);
            setStatus("Failed to load config.");
        } finally {
            setLoading(false);
        }
    };

    const handleChange = (key, value) => {
        setConfig((prev) => ({ ...prev, [key]: value }));
    };

    const handleSave = async () => {
        setLoading(true);
        setStatus('Saving...');
        try {
            await updateConfig(config);
            setStatus('Configuration saved!');
            setTimeout(() => setStatus(''), 2000);
        } catch (err) {
            console.error("Failed to save config", err);
            setStatus('Failed to save.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="card glass-card">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <Settings className="text-accent-primary" size={24} />
                    <h2 className="text-xl font-bold">System Configuration</h2>
                </div>
                <div className="flex gap-2">
                    <button onClick={fetchConfig} className="btn btn-secondary" disabled={loading}>
                        <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
                        Refresh
                    </button>
                    <button onClick={handleSave} className="btn btn-primary" disabled={loading}>
                        <Save size={18} />
                        Apply
                    </button>
                </div>
            </div>

            <div className="grid gap-4">
                {/* Fake LLM Toggle */}
                <div className="flex items-center justify-between p-4 bg-bg-dark rounded-lg border border-border">
                    <div className="flex items-center gap-3">
                        <Zap className={config.USE_FAKE_LLM ? "text-yellow-400" : "text-gray-500"} size={20} />
                        <div>
                            <div className="font-semibold">Fake LLM Provider</div>
                            <div className="text-sm text-muted">Simulated LLM for cost-free testing</div>
                        </div>
                    </div>
                    <label className="toggle-switch">
                        <input
                            type="checkbox"
                            checked={config.USE_FAKE_LLM}
                            onChange={(e) => handleChange('USE_FAKE_LLM', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                {/* Caching Toggle */}
                <div className="flex items-center justify-between p-4 bg-bg-dark rounded-lg border border-border">
                    <div className="flex items-center gap-3">
                        <Database className={config.ENABLE_CACHING ? "text-green-400" : "text-gray-500"} size={20} />
                        <div>
                            <div className="font-semibold">Multi-Tier Caching</div>
                            <div className="text-sm text-muted">L1 (Memory) & L2 (Redis) caching</div>
                        </div>
                    </div>
                    <label className="toggle-switch">
                        <input
                            type="checkbox"
                            checked={config.ENABLE_CACHING}
                            onChange={(e) => handleChange('ENABLE_CACHING', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                {/* Queue Type Selection */}
                <div className="p-4 bg-bg-dark rounded-lg border border-border">
                    <div className="flex items-center gap-3 mb-3">
                        <Server className="text-blue-400" size={20} />
                        <div>
                            <div className="font-semibold">Message Queue</div>
                            <div className="text-sm text-muted">Backend for async processing</div>
                        </div>
                    </div>
                    <div className="flex gap-3">
                        <button
                            onClick={() => handleChange('QUEUE_TYPE', 'redis')}
                            className={`btn-queue ${config.QUEUE_TYPE === 'redis' ? 'btn-queue-redis-active' : ''}`}
                        >
                            <div className={`indicator-dot ${config.QUEUE_TYPE === 'redis' ? 'active' : ''}`}></div>
                            Redis
                        </button>
                        <button
                            onClick={() => handleChange('QUEUE_TYPE', 'kafka')}
                            className={`btn-queue ${config.QUEUE_TYPE === 'kafka' ? 'btn-queue-kafka-active' : ''}`}
                        >
                            <div className={`indicator-dot ${config.QUEUE_TYPE === 'kafka' ? 'active' : ''}`}></div>
                            Kafka
                        </button>
                    </div>
                </div>

                {status && (
                    <div className="text-center text-sm font-medium text-accent-primary animate-pulse py-2">
                        {status}
                    </div>
                )}
            </div>
        </div>
    );
};

export default ConfigurationPanel;
