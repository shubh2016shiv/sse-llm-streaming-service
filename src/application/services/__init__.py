"""
Application Services Package
=============================

This package contains business logic services that are used by API routes.

WHY SERVICE LAYER?
------------------
The service layer separates business logic from HTTP/API concerns:

1. **Single Responsibility**: Routes handle HTTP, services handle business logic
2. **Testability**: Services can be tested without HTTP mocking
3. **Reusability**: Same service can be used by multiple routes or background jobs
4. **Maintainability**: Changes to business logic don't require route changes
5. **Dependency Injection**: Services can be swapped for testing/mocking

ARCHITECTURE PATTERN:
---------------------
Controller → Service → Repository/External API

- Controller (routes): HTTP request/response handling
- Service: Business logic, orchestration, aggregation
- Repository: Data access, external API calls

This follows Clean Architecture / Hexagonal Architecture principles.

GOOGLE SRE BEST PRACTICES:
--------------------------
- Services should be stateless (no instance variables for request data)
- Services should handle errors gracefully (never crash the app)
- Services should log operations for observability
- Services should have clear interfaces (type hints, docstrings)
"""

from src.application.services.config_service import ConfigService, get_config_service
from src.application.services.metrics_service import MetricsService, get_metrics_service
from src.application.services.streaming_service import StreamingService, get_streaming_service

__all__ = [
    "MetricsService",
    "get_metrics_service",
    "ConfigService",
    "get_config_service",
    "StreamingService",
    "get_streaming_service",
]
