"""
Provider Registration

Registers all available LLM providers with the factory on application startup.
"""

from src.config.settings import get_settings
from src.core.logging import get_logger
from src.llm_providers import (
    DeepSeekProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderConfig,
    get_provider_factory,
)

logger = get_logger(__name__)

def register_providers() -> None:
    """Register all available LLM providers with the global factory."""
    settings = get_settings()
    factory = get_provider_factory()

    # Register OpenAI
    if settings.llm.OPENAI_API_KEY:
        factory.register(
            name="openai",
            provider_class=OpenAIProvider,
            config=ProviderConfig(
                name="openai",
                api_key=settings.llm.OPENAI_API_KEY,
                base_url="https://api.openai.com/v1",
                default_model="gpt-3.5-turbo"
            )
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
                default_model="deepseek-chat"
            )
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
                default_model="gemini-pro"
            )
        )
        logger.info("Registered Gemini provider")
