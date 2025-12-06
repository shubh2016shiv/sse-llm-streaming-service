# Performance Experiments Walkthrough

This guide explains how to run the performance experiments using the new interactive dashboard.

## Prerequisites

- backend running (Port 8000)
- Node.js installed

## 1. Start the Backend

The backend now supports `FakeProvider` for cost-free load testing.

```bash
# Ensure you are in the project root
python infrastructure/manage.py start
```

*Note: Attempts to use real LLM keys will not occur if `USE_FAKE_LLM` is enabled (default).*

## 2. Start the Experiment Dashboard

The React dashboard allows you to configure the system and run load tests.

```bash
cd performance_experiments/dashboard
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

## 3. Running Experiments

### Experiment A: Baseline (No Architecture)
1. On the dashboard, **disable** "Multi-Tier Caching".
2. Ensure "Message Queue" is set to **Redis** (default).
3. Set Concurrency to **10** and Total Requests to **50**.
4. Click **Start Load Test**.
5. Observe the "Avg Latency" and the "Backend Execution Latency" chart.

### Experiment B: High Scale (Kafka)
1. Switch "Message Queue" to **Kafka**. *Note: Ensure Kafka container is running.*
2. Run the load test again with higher concurrency (e.g., **20**).
3. Compare throughput.

### Experiment C: Caching Impact
1. **Enable** "Multi-Tier Caching".
2. Run a load test.
3. Run it *again* immediately.
4. Observe the latency drop significantly on the second run due to L1/L2 cache hits.

## Troubleshooting

- **Backend errors**: Check `docker-compose logs backend`.
- **Dashboard API errors**: Ensure backend CORS is configured (default `*` is set).
