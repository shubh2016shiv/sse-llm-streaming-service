"""
API Models Package
==================

This package contains Pydantic models for API request/response validation.

WHY SEPARATE MODELS PACKAGE?
-----------------------------
Separating models from routes provides:

1. **Reusability**: Models can be imported by multiple routes
2. **Testing**: Easy to test models independently
3. **Documentation**: Models serve as living documentation
4. **Validation**: Centralized validation logic
5. **Maintainability**: Changes to models don't affect route logic

ORGANIZATION:
-------------
- admin.py: Admin endpoint response models
- streaming.py: Streaming endpoint request/response models
"""

from src.application.api.models.admin import *  # noqa: F401, F403
from src.application.api.models.streaming import *  # noqa: F401, F403

__all__ = [
    # Admin models (re-exported from admin.py)
    # Streaming models (re-exported from streaming.py)
]
