"""
Request Factory for Test Data

Creates consistent StreamRequest objects for testing with various scenarios.
"""


from src.llm_stream.models.stream_request import StreamRequest


class RequestFactory:
    """Factory for creating valid StreamRequest objects."""

    @staticmethod
    def basic_query(query: str = "What is AI?") -> StreamRequest:
        """Create a basic valid request."""
        return StreamRequest(
            query=query,
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="test-thread-123",
            user_id="test-user-456",
        )

    @staticmethod
    def with_provider(provider: str, model: str | None = None) -> StreamRequest:
        """Create request with specific provider."""
        model = model or f"{provider}-model"
        return StreamRequest(
            query="Test query",
            model=model,
            provider=provider,
            thread_id=f"thread-{provider}",
            user_id=f"user-{provider}",
        )

    @staticmethod
    def long_query() -> StreamRequest:
        """Create request with long query for stress testing."""
        long_text = "What is the meaning of life? " * 50
        return StreamRequest(
            query=long_text,
            model="gpt-4",
            provider="openai",
            thread_id="long-thread",
            user_id="long-user",
        )

    @staticmethod
    def batch_requests(count: int = 5) -> list[StreamRequest]:
        """Create a batch of requests for testing."""
        return [
            StreamRequest(
                query=f"Query {i}",
                model="gpt-3.5-turbo",
                provider="openai",
                thread_id=f"batch-thread-{i}",
                user_id=f"batch-user-{i}",
            )
            for i in range(count)
        ]


class ErrorRequestFactory:
    """Factory for creating invalid StreamRequest objects for error testing."""

    @staticmethod
    def empty_query() -> StreamRequest:
        """Request with empty query."""
        return StreamRequest(
            query="",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="error-thread",
            user_id="error-user",
        )

    @staticmethod
    def invalid_model() -> StreamRequest:
        """Request with invalid model."""
        return StreamRequest(
            query="Test query",
            model="invalid-model-name-that-does-not-exist",
            provider="openai",
            thread_id="error-thread",
            user_id="error-user",
        )

    @staticmethod
    def invalid_provider() -> StreamRequest:
        """Request with invalid provider."""
        return StreamRequest(
            query="Test query",
            model="gpt-3.5-turbo",
            provider="nonexistent-provider",
            thread_id="error-thread",
            user_id="error-user",
        )

    @staticmethod
    def special_characters() -> StreamRequest:
        """Request with special characters that might cause issues."""
        return StreamRequest(
            query="Query with <script>alert('xss')</script> and SQL ' OR 1=1 --",
            model="gpt-3.5-turbo",
            provider="openai",
            thread_id="special-thread",
            user_id="special-user",
        )










