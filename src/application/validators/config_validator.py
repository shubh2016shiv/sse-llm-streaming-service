"""
Configuration Validators

Validates runtime configuration updates for safety and consistency.

ENTERPRISE USE CASE: Runtime Configuration
-------------------------------------------
Admin endpoints allow runtime config updates without restart.
These validators ensure:
- Only valid configuration keys are updated
- Values are within safe ranges
- Type safety is maintained
- Breaking changes are prevented
"""

from typing import Any

from src.application.validators.base import BaseValidator
from src.application.validators.exceptions import ConfigValidationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class ConfigValidator(BaseValidator):
    """
    Validates runtime configuration updates.

    VALIDATION RULES:
    -----------------
    1. Only allowed keys can be updated
    2. Values must match expected types
    3. Values must be within safe ranges
    4. Breaking changes are prevented
    """

    # Allowed configuration keys and their constraints
    ALLOWED_CONFIG = {
        "USE_FAKE_LLM": {
            "type": bool,
            "description": "Use fake LLM for testing",
        },
        "ENABLE_CACHING": {
            "type": bool,
            "description": "Enable response caching",
        },
        "QUEUE_TYPE": {
            "type": str,
            "allowed_values": {"redis", "kafka"},
            "description": "Message queue type",
        },
        "RATE_LIMIT_DEFAULT": {
            "type": str,
            "pattern": r"^\d+/(second|minute|hour|day)$",
            "description": "Default rate limit (e.g., '100/minute')",
        },
    }

    def validate(self, config_updates: dict[str, Any]) -> None:
        """
        Validate configuration updates.

        Args:
            config_updates: Dictionary of config key-value pairs to update

        Raises:
            ConfigValidationError: If validation fails

        VALIDATION SEQUENCE:
        --------------------
        1. Check all keys are allowed
        2. Validate each value's type
        3. Validate each value's constraints
        """
        if not config_updates:
            raise ConfigValidationError("No configuration updates provided")

        for key, value in config_updates.items():
            self._validate_config_key(key, value)

        logger.info("Configuration validation passed", updates=list(config_updates.keys()))

    def _validate_config_key(self, key: str, value: Any) -> None:
        """
        Validate a single configuration key-value pair.

        ENTERPRISE PATTERN: Whitelist Validation
        -----------------------------------------
        Only explicitly allowed keys can be updated.
        This prevents:
        - Typos causing silent failures
        - Malicious config injection
        - Accidental breaking changes
        """
        # Check key is allowed
        if key not in self.ALLOWED_CONFIG:
            allowed_keys = ", ".join(self.ALLOWED_CONFIG.keys())
            raise ConfigValidationError(
                f"Configuration key '{key}' is not allowed. Allowed keys: {allowed_keys}", field=key
            )

        config_spec = self.ALLOWED_CONFIG[key]

        # Validate type
        expected_type = config_spec["type"]
        if not isinstance(value, expected_type):
            raise ConfigValidationError(
                f"Configuration '{key}' must be of type {expected_type.__name__}, "
                f"got {type(value).__name__}",
                field=key,
                value=value,
            )

        # Validate constraints
        if "allowed_values" in config_spec:
            if value not in config_spec["allowed_values"]:
                allowed = ", ".join(map(str, config_spec["allowed_values"]))
                raise ConfigValidationError(
                    f"Configuration '{key}' must be one of: {allowed}", field=key, value=value
                )

        if "pattern" in config_spec and isinstance(value, str):
            self.validate_pattern(
                value, config_spec["pattern"], key, f"Configuration '{key}' format is invalid"
            )
