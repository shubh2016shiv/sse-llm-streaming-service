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
        <div className="bg-bg-card border border-border rounded-xl shadow-lg">
            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-blue-500/20">
                            <Settings className="text-accent-primary" size={24} />
                        </div>
                        <h2 className="text-xl font-bold">System Configuration</h2>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={fetchConfig}
                            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-text-primary bg-bg-tertiary border border-border rounded-lg hover:bg-border-hover transition-colors disabled:opacity-50"
                            disabled={loading}
                            aria-label="Refresh configuration"
                        >
                            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
                            Refresh
                        </button>
                        <button
                            onClick={handleSave}
                            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                            style={{ background: 'linear-gradient(135deg, var(--primary-blue), var(--primary-purple))' }}
                            disabled={loading}
                            aria-label="Apply configuration changes"
                        >
                            <Save size={16} />
                            Apply
                        </button>
                    </div>
                </div>

                <div className="space-y-4">
                    {/* Fake LLM Toggle */}
                    <div className="flex items-center justify-between p-4 bg-bg-dark rounded-lg border border-border">
                        <div className="flex items-center gap-3">
                            <Zap className={config.USE_FAKE_LLM ? "text-yellow-400" : "text-gray-500"} size={20} />
                            <div>
                                <div className="font-semibold">Fake LLM Provider</div>
                                <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Simulated LLM for cost-free testing</div>
                            </div>
                        </div>
                        <label className="toggle-switch" aria-label="Toggle Fake LLM Provider">
                            <input
                                type="checkbox"
                                checked={config.USE_FAKE_LLM}
                                onChange={(e) => handleChange('USE_FAKE_LLM', e.target.checked)}
                                aria-checked={config.USE_FAKE_LLM}
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
                                <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>L1 (Memory) & L2 (Redis) caching</div>
                            </div>
                        </div>
                        <label className="toggle-switch" aria-label="Toggle Multi-Tier Caching">
                            <input
                                type="checkbox"
                                checked={config.ENABLE_CACHING}
                                onChange={(e) => handleChange('ENABLE_CACHING', e.target.checked)}
                                aria-checked={config.ENABLE_CACHING}
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
                                <div className="text-sm text-text-secondary">Backend for async processing</div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={() => handleChange('QUEUE_TYPE', 'redis')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                                    config.QUEUE_TYPE === 'redis'
                                        ? 'bg-blue-600 text-white shadow-md'
                                        : 'bg-bg-tertiary text-text-secondary hover:bg-border-hover'
                                }`}
                                aria-pressed={config.QUEUE_TYPE === 'redis'}
                            >
                                <div className={`w-2 h-2 rounded-full ${config.QUEUE_TYPE === 'redis' ? 'bg-white' : 'bg-gray-500'}`}></div>
                                Redis
                            </button>
                            <button
                                onClick={() => handleChange('QUEUE_TYPE', 'kafka')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                                    config.QUEUE_TYPE === 'kafka'
                                        ? 'bg-purple-600 text-white shadow-md'
                                        : 'bg-bg-tertiary text-text-secondary hover:bg-border-hover'
                                }`}
                                aria-pressed={config.QUEUE_TYPE === 'kafka'}
                            >
                                <div className={`w-2 h-2 rounded-full ${config.QUEUE_TYPE === 'kafka' ? 'bg-white' : 'bg-gray-500'}`}></div>
                                Kafka
                            </button>
                        </div>
                    </div>

                    {/* Status Message */}
                    {status && (
                        <div className="text-center py-2">
                            {status === 'Configuration saved!' ? (
                                <div className="status-badge status-badge-success inline-flex items-center gap-2">
                                    <span>✓</span>
                                    {status}
                                </div>
                            ) : status === 'Failed to save.' || status === 'Failed to load config.' ? (
                                <div className="status-badge status-badge-error inline-flex items-center gap-2">
                                    <span>✗</span>
                                    {status}
                                </div>
                            ) : (
                                <div className="status-badge status-badge-info inline-flex items-center gap-2">
                                    <div className="loading-spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div>
                                    {status}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ConfigurationPanel;
