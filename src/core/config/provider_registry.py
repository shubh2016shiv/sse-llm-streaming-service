"""
LLM Provider Registry

This module handles the registration of all available LLM providers (OpenAI, DeepSeek, Gemini, Fake)
with the provider factory during application startup.

Architectural Decision: Centralized provider registration
- Single location for all provider configurations
- Conditional registration based on API key availability
- Supports multiple providers simultaneously
- Easy to add new providers

Author: System Architect
Date: 2025-12-05
"""

from src.core.config.settings import get_settings
from src.core.logging.logger import get_logger
from src.llm_providers import (
    DeepSeekProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderConfig,
    get_provider_factory,
)

logger = get_logger(__name__)


def register_providers(factory=None) -> None:
    """
    Register all available LLM providers with the factory.

    Args:
        factory: Optional ProviderFactory instance. If None, uses global factory.
    """
    settings = get_settings()
    factory = factory or get_provider_factory()

    # Register OpenAI
    if settings.llm.OPENAI_API_KEY:
        factory.register(
            name="openai",
            provider_class=OpenAIProvider,
            config=ProviderConfig(
                name="openai",
                api_key=settings.llm.OPENAI_API_KEY,
                base_url="https://api.openai.com/v1",
                default_model="gpt-3.5-turbo",
            ),
        )
        logger.info("Registered OpenAI provider")

    # Register DeepSeek
    if settings.llm.DEEPSEEK_API_KEY:
        factory.register(
            name="deepseek",
            provider_class=DeepSeekProvider,
            config=ProviderConfig(
                name="deepseek",
                api_key=settings.llm.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com/v1",
                default_model="deepseek-chat",
            ),
        )
        logger.info("Registered DeepSeek provider")

    # Register Gemini
    if settings.llm.GOOGLE_API_KEY:
        factory.register(
            name="gemini",
            provider_class=GeminiProvider,
            config=ProviderConfig(
                name="gemini",
                api_key=settings.llm.GOOGLE_API_KEY,
                base_url="",  # Not used by SDK
                default_model="gemini-pro",
            ),
        )
        logger.info("Registered Gemini provider")

    # Register Fake Provider (Experiment Mode)
    if settings.USE_FAKE_LLM:
        from src.llm_providers.fake_provider import FakeProvider

        factory.register(
            name="fake",
            provider_class=FakeProvider,
            config=ProviderConfig(
                name="fake", api_key="fake-key", base_url="fake-url", default_model="fake-model"
            ),
        )
        logger.info("Registered Fake provider for experiments")
