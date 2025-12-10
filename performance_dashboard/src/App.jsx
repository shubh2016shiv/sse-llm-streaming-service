import React from 'react';
import ConfigurationPanel from './components/ConfigurationPanel';
import LoadTester from './components/LoadTester';
import MetricsChart from './components/MetricsChart';
import BackendStatusIndicator from './components/BackendStatusIndicator';

function App() {
  return (
    <div className="min-h-screen p-4 sm:p-8 bg-bg-dark text-text-primary">
      <div className="max-w-7xl mx-auto">
        <header className="mb-10 text-center">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-purple-500 to-pink-500">
            Performance Experiments Dashboard
          </h1>
          <p className="text-base sm:text-lg text-text-secondary mb-6">
            Compare architectural patterns for High-Concurrency SSE Streaming
          </p>

          <div className="flex justify-center">
            <BackendStatusIndicator />
          </div>
        </header>

        <main className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="flex flex-col gap-6">
            <ConfigurationPanel />
            <MetricsChart />
          </div>

          <div className="lg:col-span-2">
            <LoadTester />
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;
