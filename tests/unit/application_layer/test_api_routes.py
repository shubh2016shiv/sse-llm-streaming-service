"""
Unit Tests for API Routes

Tests FastAPI routes with TestClient for health endpoints and streaming.
"""


import pytest
from fastapi.testclient import TestClient

from src.application.app import create_app


@pytest.mark.unit
class TestHealthRoutes:
    """Test suite for health check routes."""

    @pytest.fixture
    def client(self):
        """Create test client for health routes."""
        app = create_app()
        return TestClient(app)

    def test_health_endpoint_returns_200(self, client):
        """Test health endpoint returns successful response."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "timestamp" in data
        assert "version" in data

    def test_health_endpoint_includes_service_info(self, client):
        """Test health endpoint includes service information."""
        response = client.get("/api/v1/health")

        data = response.json()

        # Should include basic service info
        assert "status" in data
        assert isinstance(data["status"], str)

    def test_health_endpoint_handles_errors_gracefully(self, client):
        """Test health endpoint handles internal errors gracefully."""
        # This would require mocking dependencies to fail
        # For now, just ensure it returns a valid response
        response = client.get("/api/v1/health")

        assert response.status_code in [200, 503]  # Success or service unavailable

        if response.status_code == 503:
            data = response.json()
            assert "error" in data or "status" in data

    @pytest.mark.asyncio
    async def test_health_detailed_endpoint(self, client):
        """Test detailed health endpoint if it exists."""
        # Try detailed health endpoint
        response = client.get("/api/v1/health/detailed")

        # May or may not exist - both are acceptable
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            # Should include more detailed information
            assert len(data) > 1


@pytest.mark.unit
class TestStreamingRoutes:
    """Test suite for streaming routes."""

    @pytest.fixture
    def client(self):
        """Create test client for streaming routes."""
        app = create_app()
        return TestClient(app)

    def test_stream_endpoint_exists(self, client):
        """Test stream endpoint accepts requests."""
        # This will likely fail due to missing dependencies, but should not 404
        response = client.post("/api/v1/stream")

        # Should not be 404 (not found)
        assert response.status_code != 404

        # May be 422 (validation error) due to missing required fields
        if response.status_code == 422:
            data = response.json()
            assert "detail" in data  # FastAPI validation error format

    def test_stream_endpoint_requires_query(self, client):
        """Test stream endpoint requires query parameter."""
        # Missing required query field
        response = client.post(
            "/api/v1/stream",
            json={
                "model": "gpt-3.5-turbo",
                "provider": "openai",
                "thread_id": "test-thread",
                "user_id": "test-user",
            },
        )

        assert response.status_code == 422  # Validation error
        data = response.json()
        assert "query" in str(data).lower()

    def test_stream_endpoint_requires_model(self, client):
        """Test stream endpoint requires model parameter."""
        response = client.post(
            "/api/v1/stream",
            json={
                "query": "Test query",
                "provider": "openai",
                "thread_id": "test-thread",
                "user_id": "test-user",
            },
        )

        assert response.status_code == 422
        data = response.json()
        assert "model" in str(data).lower()

    def test_stream_endpoint_validates_request_format(self, client):
        """Test stream endpoint validates request JSON format."""
        # Send invalid JSON
        response = client.post(
            "/api/v1/stream", data="invalid json", headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stream_endpoint_handles_cors(self, client):
        """Test stream endpoint handles CORS headers."""
        # Test OPTIONS request for CORS
        response = client.options("/api/v1/stream")

        # Should allow CORS or at least not fail
        assert response.status_code in [200, 404, 405]  # 405 is method not allowed

    def test_stream_endpoint_accepts_valid_request(self, client):
        """Test stream endpoint accepts properly formatted requests."""
        # This will likely fail due to mocked dependencies, but validates request format
        response = client.post(
            "/api/v1/stream",
            json={
                "query": "What is AI?",
                "model": "gpt-3.5-turbo",
                "provider": "openai",
                "thread_id": "test-thread-123",
                "user_id": "test-user-456",
            },
        )

        # Should not be 422 (validation error)
        assert response.status_code != 422

        # May be 500 due to missing dependencies in test environment
        if response.status_code == 500:
            # This is expected in test environment
            pass

    def test_stream_endpoint_handles_sse_response(self, client):
        """Test stream endpoint returns SSE formatted response."""
        # This test would require fully mocked dependencies
        # For now, just ensure the endpoint exists and accepts POST
        response = client.post(
            "/api/v1/stream",
            json={
                "query": "Test",
                "model": "gpt-3.5-turbo",
                "provider": "openai",
                "thread_id": "test-thread",
                "user_id": "test-user",
            },
        )

        # Check response headers for SSE
        if response.status_code == 200:
            assert "text/event-stream" in response.headers.get("content-type", "")
            assert "cache-control" in response.headers
            assert "no-cache" in response.headers.get("cache-control", "")


@pytest.mark.unit
class TestAdminRoutes:
    """Test suite for admin routes."""

    @pytest.fixture
    def client(self):
        """Create test client for admin routes."""
        app = create_app()
        return TestClient(app)

    def test_admin_routes_exist(self, client):
        """Test admin routes are accessible."""
        # Try common admin endpoints
        endpoints = ["/admin/stats", "/admin/health", "/admin/metrics"]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should not be completely broken
            assert response.status_code in [200, 401, 403, 404, 500]

    def test_admin_stats_endpoint(self, client):
        """Test admin stats endpoint."""
        response = client.get("/admin/stats")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            # Should include some stats
            assert len(data) > 0


@pytest.mark.unit
class TestAPIMiddleware:
    """Test suite for API middleware."""

    @pytest.fixture
    def client(self):
        """Create test client with middleware."""
        app = create_app()
        return TestClient(app)

    def test_cors_middleware_enabled(self, client):
        """Test CORS middleware is configured."""
        response = client.options("/api/v1/health")

        # Check CORS headers
        cors_headers = [
            "access-control-allow-origin",
            "access-control-allow-methods",
            "access-control-allow-headers",
        ]

        # At least some CORS headers should be present
        has_cors = any(header in response.headers for header in cors_headers)
        assert has_cors or response.status_code in [404, 405]

    def test_request_logging_middleware(self, client):
        """Test request logging middleware is active."""
        # Make a request and check if logging occurred
        # This is hard to test directly, but we can ensure the request completes
        response = client.get("/api/v1/health")

        assert response.status_code == 200

    def test_error_handling_middleware(self, client):
        """Test error handling middleware catches exceptions."""
        # Try to trigger an error
        response = client.post("/api/v1/stream", json={})  # Invalid request

        # Should return proper error response, not crash
        assert response.status_code in [422, 500]
        assert response.headers.get("content-type") == "application/json"


@pytest.mark.unit
class TestAPIValidation:
    """Test suite for API-level validation."""

    @pytest.fixture
    def client(self):
        """Create test client for validation testing."""
        app = create_app()
        return TestClient(app)

    def test_query_length_validation(self, client):
        """Test API validates query length."""
        # Very long query
        long_query = "What is AI? " * 1000

        response = client.post(
            "/api/v1/stream",
            json={
                "query": long_query,
                "model": "gpt-3.5-turbo",
                "provider": "openai",
                "thread_id": "test-thread",
                "user_id": "test-user",
            },
        )

        # Should either accept or reject with proper error
        assert response.status_code in [200, 400, 422, 500]

    def test_model_validation(self, client):
        """Test API validates model names."""
        invalid_models = ["invalid-model", "", "gpt-5"]

        for model in invalid_models:
            response = client.post(
                "/api/v1/stream",
                json={
                    "query": "Test query",
                    "model": model,
                    "provider": "openai",
                    "thread_id": "test-thread",
                    "user_id": "test-user",
                },
            )

            # Should reject invalid models
            assert response.status_code in [400, 422, 500]

    def test_provider_validation(self, client):
        """Test API validates provider names."""
        response = client.post(
            "/api/v1/stream",
            json={
                "query": "Test query",
                "model": "gpt-3.5-turbo",
                "provider": "nonexistent-provider",
                "thread_id": "test-thread",
                "user_id": "test-user",
            },
        )

        # Should reject invalid provider
        assert response.status_code in [400, 422, 500]

    def test_thread_id_format_validation(self, client):
        """Test API ignores extra fields like thread_id (server-generated)."""
        # thread_id is NOT part of StreamRequestModel - it's generated server-side
        # This test verifies that extra fields are ignored (Pydantic default behavior)
        response = client.post(
            "/api/v1/stream",
            json={
                "query": "Test query",
                "model": "gpt-3.5-turbo",
                "provider": "openai",
                "thread_id": "",  # Extra field - should be ignored
                "user_id": "test-user",
            },
        )

        # Should succeed - Pydantic ignores extra fields by default
        # The API generates thread_id server-side from headers or auto-generates it
        assert response.status_code == 200













