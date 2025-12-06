#!/usr/bin/env python3
"""
Centralized Configuration Module using Pydantic Settings

This module provides type-safe, environment-based configuration for the entire
SSE streaming microservice. All configuration is centralized here to ensure
consistency across modules.

Architectural Decision: Pydantic Settings for type safety and validation
- Environment variable loading with .env support
- Type validation at startup (fail fast on misconfiguration)
- IDE autocomplete for all settings
- Easy testing with override mechanisms

Author: System Architect
Date: 2025-12-05
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    """
    Redis configuration for distributed caching and state management.

    STAGE-0.1: Redis connection configuration

    Architectural Decision: Connection pooling for performance
    - Min connections: 10 (always warm)
    - Max connections: 200 (increased from 100 to handle high-scale scenarios)
    - Health checks: Every 30s

    Optimization: Increased max connections to 200 to better handle
    connection spikes and reduce pool exhaustion risk at scale.
    """

    REDIS_HOST: str = Field(default="localhost", description="Redis server host")
    REDIS_PORT: int = Field(default=6379, description="Redis server port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_PASSWORD: str | None = Field(default=None, description="Redis password (if required)")

    # Connection pool settings (optimized for scale)
    REDIS_MIN_CONNECTIONS: int = Field(default=10, description="Minimum idle connections")
    REDIS_MAX_CONNECTIONS: int = Field(default=200, description="Maximum total connections (optimized for scale)")
    REDIS_SOCKET_TIMEOUT: int = Field(default=5, description="Socket timeout in seconds")
    REDIS_SOCKET_CONNECT_TIMEOUT: int = Field(default=5, description="Connection timeout in seconds")
    REDIS_HEALTH_CHECK_INTERVAL: int = Field(default=30, description="Health check interval in seconds")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class LLMProviderSettings(BaseSettings):
    """
    LLM Provider API configurations.

    STAGE-0.2: LLM provider configuration

    Supports: OpenAI, DeepSeek, Google Gemini
    """

    # OpenAI
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1", description="OpenAI base URL")
    OPENAI_TIMEOUT: int = Field(default=30, description="OpenAI request timeout")

    # DeepSeek
    DEEPSEEK_API_KEY: str | None = Field(default=None, description="DeepSeek API key")
    DEEP_SEEK: str | None = Field(default=None, description="DeepSeek API key (alternative)")
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1", description="DeepSeek base URL")
    DEEPSEEK_TIMEOUT: int = Field(default=30, description="DeepSeek request timeout")

    # Google Gemini
    GOOGLE_API_KEY: str | None = Field(default=None, description="Google Gemini API key")
    GEMINI_BASE_URL: str = Field(
        default="https://generativelanguage.googleapis.com",
        description="Gemini base URL"
    )
    GEMINI_TIMEOUT: int = Field(default=30, description="Gemini request timeout")

    @field_validator("DEEPSEEK_API_KEY", mode="before")
    @classmethod
    def merge_deepseek_keys(cls, v, info):
        """Merge DEEPSEEK_API_KEY and DEEP_SEEK for backward compatibility."""
        if v is None and info.data.get("DEEP_SEEK"):
            return info.data["DEEP_SEEK"]
        return v

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class CircuitBreakerSettings(BaseSettings):
    """
    Circuit breaker configuration for fault tolerance.

    STAGE-CB: Circuit breaker thresholds

    Architectural Decision: pybreaker with Redis backend
    - Distributed state across all instances
    - Coordinated failure detection
    """

    CB_FAILURE_THRESHOLD: int = Field(default=5, description="Failures before opening circuit")
    CB_RECOVERY_TIMEOUT: int = Field(default=60, description="Seconds before attempting recovery")
    CB_SUCCESS_THRESHOLD: int = Field(default=2, description="Successes to close circuit")
    CB_TIMEOUT: int = Field(default=30, description="Request timeout in seconds")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class RateLimitSettings(BaseSettings):
    """
    Rate limiting configuration.

    STAGE-3: Rate limiting thresholds

    Architectural Decision: slowapi with Redis backend
    - Token bucket algorithm (moving window)
    - Per-user and per-IP limits
    """

    RATE_LIMIT_DEFAULT: str = Field(default="100/minute", description="Default rate limit")
    RATE_LIMIT_PREMIUM: str = Field(default="1000/minute", description="Premium user rate limit")
    RATE_LIMIT_BURST: int = Field(default=20, description="Burst allowance")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class CacheSettings(BaseSettings):
    """
    Caching configuration for multi-tier caching strategy.

    STAGE-2: Cache TTL configuration

    Optimization: Different TTLs for different content types
    """

    CACHE_RESPONSE_TTL: int = Field(default=3600, description="Response cache TTL (1 hour)")
    CACHE_SESSION_TTL: int = Field(default=86400, description="Session cache TTL (24 hours)")
    CACHE_L1_MAX_SIZE: int = Field(default=1000, description="L1 in-memory cache max entries")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class ExecutionTrackingSettings(BaseSettings):
    """
    Execution tracking configuration for performance monitoring and sampling.

    STAGE-ET: Execution tracking configuration

    Architectural Decision: Probabilistic sampling for reduced memory usage
    - 10% default sample rate (configurable)
    - Maintains full tracking for sampled requests
    - Hash-based sampling ensures consistent tracking per thread_id
    """

    EXECUTION_TRACKING_ENABLED: bool = Field(default=True, description="Enable execution tracking")
    EXECUTION_TRACKING_SAMPLE_RATE: float = Field(default=0.1, description="Sampling rate (0.0-1.0), 0.1 = 10%")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class LoggingSettings(BaseSettings):
    """
    Logging configuration for structured logging.

    STAGE-L: Logging configuration

    Architectural Decision: structlog for production-grade logging
    """

    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: Literal["json", "console"] = Field(default="json", description="Log output format")
    LOG_FILE: str | None = Field(default=None, description="Log file path (optional)")

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class ApplicationSettings(BaseSettings):
    """
    General application settings.

    STAGE-0: Application initialization
    """

    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Application environment"
    )
    DEBUG: bool = Field(default=False, description="Debug mode")
    APP_NAME: str = Field(default="SSE Streaming Microservice", description="Application name")
    APP_VERSION: str = Field(default="1.0.0", description="Application version")

    # API settings
    API_HOST: str = Field(default="0.0.0.0", description="API host")
    API_PORT: int = Field(default=8000, description="API port")

    # CORS settings
    CORS_ORIGINS: list[str] = Field(default=["*"], description="Allowed CORS origins")

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)


class Settings(BaseSettings):
    """
    Main settings class that aggregates all configuration sections.

    STAGE-0: Centralized configuration initialization

    Usage:
        from config.settings import get_settings

        settings = get_settings()
        redis_host = settings.redis.REDIS_HOST
        openai_key = settings.llm.OPENAI_API_KEY

    Architectural Benefits:
    - Single source of truth for all configuration
    - Type-safe access with IDE autocomplete
    - Validation at startup (fail fast)
    - Easy testing with override mechanisms
    - Environment-specific configurations
    """

    # Redis settings
    REDIS_HOST: str = Field(default="localhost", description="Redis server host")
    REDIS_PORT: int = Field(default=6379, description="Redis server port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_PASSWORD: str | None = Field(default=None, description="Redis password (if required)")
    REDIS_MIN_CONNECTIONS: int = Field(default=10, description="Minimum idle connections")
    REDIS_MAX_CONNECTIONS: int = Field(default=200, description="Maximum total connections (optimized for scale)")
    REDIS_SOCKET_TIMEOUT: int = Field(default=5, description="Socket timeout in seconds")
    REDIS_SOCKET_CONNECT_TIMEOUT: int = Field(default=5, description="Connection timeout in seconds")
    REDIS_HEALTH_CHECK_INTERVAL: int = Field(default=30, description="Health check interval in seconds")

    # LLM Provider settings
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1", description="OpenAI base URL")
    OPENAI_TIMEOUT: int = Field(default=30, description="OpenAI request timeout")

    DEEPSEEK_API_KEY: str | None = Field(default=None, description="DeepSeek API key")
    DEEP_SEEK: str | None = Field(default=None, description="DeepSeek API key (alternative)")
    DEEPSEEK_BASE_URL: str = Field(default="https://api.deepseek.com/v1", description="DeepSeek base URL")
    DEEPSEEK_TIMEOUT: int = Field(default=30, description="DeepSeek request timeout")

    GOOGLE_API_KEY: str | None = Field(default=None, description="Google Gemini API key")
    GEMINI_BASE_URL: str = Field(
        default="https://generativelanguage.googleapis.com",
        description="Gemini base URL"
    )
    GEMINI_TIMEOUT: int = Field(default=30, description="Gemini request timeout")

    # Circuit Breaker settings
    CB_FAILURE_THRESHOLD: int = Field(default=5, description="Failures before opening circuit")
    CB_RECOVERY_TIMEOUT: int = Field(default=60, description="Seconds before attempting recovery")
    CB_SUCCESS_THRESHOLD: int = Field(default=2, description="Successes to close circuit")
    CB_TIMEOUT: int = Field(default=30, description="Request timeout in seconds")

    # Rate Limiting settings
    RATE_LIMIT_DEFAULT: str = Field(default="100/minute", description="Default rate limit")
    RATE_LIMIT_PREMIUM: str = Field(default="1000/minute", description="Premium user rate limit")
    RATE_LIMIT_BURST: int = Field(default=20, description="Burst allowance")

    # Cache settings
    CACHE_RESPONSE_TTL: int = Field(default=3600, description="Response cache TTL (1 hour)")
    CACHE_SESSION_TTL: int = Field(default=86400, description="Session cache TTL (24 hours)")
    CACHE_L1_MAX_SIZE: int = Field(default=1000, description="L1 in-memory cache max entries")

    # Execution Tracking settings
    EXECUTION_TRACKING_ENABLED: bool = Field(default=True, description="Enable execution tracking")
    EXECUTION_TRACKING_SAMPLE_RATE: float = Field(default=0.1, description="Sampling rate (0.0-1.0), 0.1 = 10%")

    # Rate Limiting Local Cache settings
    RATE_LIMIT_LOCAL_CACHE_ENABLED: bool = Field(default=True, description="Enable local rate limit cache")
    RATE_LIMIT_LOCAL_SYNC_INTERVAL: int = Field(default=1, description="Local cache sync interval (seconds)")

    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: Literal["json", "console"] = Field(default="json", description="Log output format")
    LOG_FILE: str | None = Field(default=None, description="Log file path (optional)")

    # Application settings
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Application environment"
    )
    DEBUG: bool = Field(default=False, description="Debug mode")
    APP_NAME: str = Field(default="SSE Streaming Microservice", description="Application name")
    APP_VERSION: str = Field(default="1.0.0", description="Application version")
    API_HOST: str = Field(default="0.0.0.0", description="API host")
    API_PORT: int = Field(default=8000, description="API port")
    CORS_ORIGINS: list[str] = Field(default=["*"], description="Allowed CORS origins")

    @model_validator(mode="after")
    def merge_deepseek_keys(self):
        """Merge DEEPSEEK_API_KEY and DEEP_SEEK for backward compatibility."""
        if self.DEEPSEEK_API_KEY is None and self.DEEP_SEEK:
            self.DEEPSEEK_API_KEY = self.DEEP_SEEK
        return self

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()

    # Nested configuration objects for backward compatibility
    @property
    def redis(self) -> 'RedisSettings':
        """Get Redis settings."""
        return RedisSettings(
            REDIS_HOST=self.REDIS_HOST,
            REDIS_PORT=self.REDIS_PORT,
            REDIS_DB=self.REDIS_DB,
            REDIS_PASSWORD=self.REDIS_PASSWORD,
            REDIS_MIN_CONNECTIONS=self.REDIS_MIN_CONNECTIONS,
            REDIS_MAX_CONNECTIONS=max(self.REDIS_MAX_CONNECTIONS, 200),
            REDIS_SOCKET_TIMEOUT=self.REDIS_SOCKET_TIMEOUT,
            REDIS_SOCKET_CONNECT_TIMEOUT=self.REDIS_SOCKET_CONNECT_TIMEOUT,
            REDIS_HEALTH_CHECK_INTERVAL=self.REDIS_HEALTH_CHECK_INTERVAL
        )

    @property
    def llm(self) -> 'LLMProviderSettings':
        """Get LLM provider settings."""
        return LLMProviderSettings(
            OPENAI_API_KEY=self.OPENAI_API_KEY,
            OPENAI_BASE_URL=self.OPENAI_BASE_URL,
            OPENAI_TIMEOUT=self.OPENAI_TIMEOUT,
            DEEPSEEK_API_KEY=self.DEEPSEEK_API_KEY,
            DEEP_SEEK=self.DEEP_SEEK,
            DEEPSEEK_BASE_URL=self.DEEPSEEK_BASE_URL,
            DEEPSEEK_TIMEOUT=self.DEEPSEEK_TIMEOUT,
            GOOGLE_API_KEY=self.GOOGLE_API_KEY,
            GEMINI_BASE_URL=self.GEMINI_BASE_URL,
            GEMINI_TIMEOUT=self.GEMINI_TIMEOUT
        )

    @property
    def circuit_breaker(self) -> 'CircuitBreakerSettings':
        """Get circuit breaker settings."""
        return CircuitBreakerSettings(
            CB_FAILURE_THRESHOLD=self.CB_FAILURE_THRESHOLD,
            CB_RECOVERY_TIMEOUT=self.CB_RECOVERY_TIMEOUT,
            CB_SUCCESS_THRESHOLD=self.CB_SUCCESS_THRESHOLD,
            CB_TIMEOUT=self.CB_TIMEOUT
        )

    @property
    def rate_limit(self) -> 'RateLimitSettings':
        """Get rate limit settings."""
        return RateLimitSettings(
            RATE_LIMIT_DEFAULT=self.RATE_LIMIT_DEFAULT,
            RATE_LIMIT_PREMIUM=self.RATE_LIMIT_PREMIUM,
            RATE_LIMIT_BURST=self.RATE_LIMIT_BURST
        )

    @property
    def cache(self) -> 'CacheSettings':
        """Get cache settings."""
        return CacheSettings(
            CACHE_RESPONSE_TTL=self.CACHE_RESPONSE_TTL,
            CACHE_SESSION_TTL=self.CACHE_SESSION_TTL,
            CACHE_L1_MAX_SIZE=self.CACHE_L1_MAX_SIZE
        )

    @property
    def logging(self) -> 'LoggingSettings':
        """Get logging settings."""
        return LoggingSettings(
            LOG_LEVEL=self.LOG_LEVEL,
            LOG_FORMAT=self.LOG_FORMAT,
            LOG_FILE=self.LOG_FILE
        )

    @property
    def app(self) -> 'ApplicationSettings':
        """Get application settings."""
        return ApplicationSettings(
            ENVIRONMENT=self.ENVIRONMENT,
            DEBUG=self.DEBUG,
            APP_NAME=self.APP_NAME,
            APP_VERSION=self.APP_VERSION,
            API_HOST=self.API_HOST,
            API_PORT=self.API_PORT,
            CORS_ORIGINS=self.CORS_ORIGINS
        )

    @property
    def execution_tracking(self) -> 'ExecutionTrackingSettings':
        """Get execution tracking settings."""
        return ExecutionTrackingSettings(
            EXECUTION_TRACKING_ENABLED=self.EXECUTION_TRACKING_ENABLED,
            EXECUTION_TRACKING_SAMPLE_RATE=self.EXECUTION_TRACKING_SAMPLE_RATE
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ignore extra environment variables
    )


# Global settings instance (singleton pattern)
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get the global settings instance (singleton).

    STAGE-0.3: Settings initialization

    Returns:
        Settings: Global settings instance

    Architectural Decision: Singleton pattern for settings
    - Single instance shared across application
    - Lazy initialization
    - Thread-safe (Python GIL)
    """
    global _settings

    if _settings is None:
        _settings = Settings()

    return _settings


def reload_settings() -> Settings:
    """
    Reload settings (useful for testing).

    Returns:
        Settings: New settings instance
    """
    global _settings
    _settings = Settings()
    return _settings


# Convenience function for getting settings
settings = get_settings()


