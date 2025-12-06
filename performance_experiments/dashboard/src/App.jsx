import React from 'react';
import ConfigurationPanel from './components/ConfigurationPanel';
import LoadTester from './components/LoadTester';
import MetricsChart from './components/MetricsChart';

function App() {
  return (
    <div className="min-h-screen p-8 bg-bg-dark text-text-primary">
      <div className="container">
        <header className="mb-10 text-center">
          <h1 className="text-4xl font-black mb-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-purple-500 to-pink-500">
            Performance Experiments Dashboard
          </h1>
          <p className="text-text-secondary text-lg">
            Compare architectural patterns for High-Concurrency SSE Streaming
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column: Configuration & Stats */}
          <div className="space-y-8">
            <ConfigurationPanel />
            <MetricsChart />
          </div>

          {/* Right Column: Load Tester */}
          <div className="lg:col-span-2">
            <LoadTester />

            {/* Guide */}
            <div className="mt-8 p-6 rounded-xl border border-dashed border-gray-700 bg-gray-900/50">
              <h3 className="text-lg font-bold mb-2 text-gray-300">Experiment Guide</h3>
              <ol className="list-decimal pl-5 space-y-2 text-sm text-gray-400">
                <li>
                  <strong className="text-blue-400">Baseline (No Caching, No Kafka):</strong>
                  Disable Caching, set Queue to Redis (standard). Run load test. Observe latency.
                </li>
                <li>
                  <strong className="text-green-400">With Caching:</strong>
                  Enable Caching. Run same load test. 2nd run for same prompts should be instant (L1/L2 hits).
                </li>
                <li>
                  <strong className="text-purple-400">With Kafka (High Scale):</strong>
                  Set Queue to Kafka. Useful for very high concurrency to decouple ingestion from processing.
                </li>
              </ol>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
