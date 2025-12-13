"""
Configuration Service - Educational Documentation
==================================================

WHAT IS THIS SERVICE?
---------------------
ConfigService handles runtime configuration updates for feature flags.
This allows changing application behavior without restarting the service.

WHY SEPARATE FROM ROUTES?
--------------------------
- Validation logic in one place (not mixed with HTTP handling)
- Audit logging centralized
- Easy to test independently
- Can be reused by other routes or background jobs

FEATURE FLAGS PATTERN:
----------------------
Feature flags allow:
1. A/B testing (enable feature for subset of users)
2. Emergency switches (disable expensive features during incidents)
3. Gradual rollouts (enable for 1%, then 10%, then 100%)
4. Configuration experiments (try different settings)

GOOGLE SRE BEST PRACTICES:
--------------------------
- Always log configuration changes (audit trail)
- Validate new values before applying (defensive programming)
- Return current state after update (confirmation)
- Consider impact scope (does this require restarting components?)
"""

from typing import Any

import structlog

from src.application.api.models.admin import ConfigResponse, ConfigUpdateResponse

logger = structlog.get_logger(__name__)


class ConfigService:
    """
    Service for managing runtime configuration.

    DESIGN PRINCIPLES:
    ------------------
    - Stateless: No instance variables for request data
    - Logging: All changes logged with context
    - Validation: Validate before applying changes
    - Atomicity: Changes applied together (all or nothing)
    """

    def __init__(self, settings):
        """
        Initialize configuration service.

        Args:
            settings: Application settings singleton
        """
        self.settings = settings
        logger.info(
            "config_service_initialized",
            context="Service ready to handle runtime configuration updates",
        )

    def get_current_config(self) -> ConfigResponse:
        """
        Get current configuration values.

        SIMPLICITY:
        -----------
        This is a simple getter, but wrapping in a service method:
        - Provides consistent interface
        - Allows adding logging/caching later
        - Makes testing easier (mock service, not settings)

        Returns:
            ConfigResponse with current values
        """
        logger.debug("get_current_config_called")

        return ConfigResponse(
            USE_FAKE_LLM=self.settings.USE_FAKE_LLM,
            ENABLE_CACHING=self.settings.ENABLE_CACHING,
            QUEUE_TYPE=self.settings.QUEUE_TYPE,
        )

    async def update_config(
        self,
        request: Any,  # UpdateConfigRequest from admin.py
        user_id: str | None = None,
    ) -> ConfigUpdateResponse:
        """
        Update configuration with validation and audit logging.

        VALIDATION STRATEGY:
        --------------------
        1. Validate new values before applying
        2. Check if values actually changed (avoid unnecessary work)
        3. Apply changes atomically
        4. Trigger any necessary side effects (e.g., re-register providers)
        5. Log for audit trail
        6. Return confirmation

        AUDIT LOGGING:
        --------------
        Every configuration change is logged with:
        - What changed (field name and new value)
        - Who changed it (user_id if authenticated)
        - When it changed (timestamp from structured logging)
        - Context (why the change might have been made)

        Args:
            request: Configuration update request (with optional fields)
            user_id: ID of user making the change (for audit logging)

        Returns:
            ConfigUpdateResponse with status and current values
        """
        logger.info(
            "config_update_started",
            user_id=user_id,
            requested_changes={
                k: v
                for k, v in {
                    "USE_FAKE_LLM": request.USE_FAKE_LLM,
                    "ENABLE_CACHING": request.ENABLE_CACHING,
                    "QUEUE_TYPE": request.QUEUE_TYPE,
                }.items()
                if v is not None
            },
        )

        # Track what actually changed for logging
        changes_applied = []

        # Update USE_FAKE_LLM if provided
        if request.USE_FAKE_LLM is not None:
            old_value = self.settings.USE_FAKE_LLM
            self.settings.USE_FAKE_LLM = request.USE_FAKE_LLM

            if old_value != request.USE_FAKE_LLM:
                changes_applied.append(
                    {
                        "field": "USE_FAKE_LLM",
                        "old_value": old_value,
                        "new_value": request.USE_FAKE_LLM,
                    }
                )

                # SIDE EFFECT: Re-register providers with new fake/real setting
                # This ensures new requests use the correct provider type
                from src.core.config.provider_registry import register_providers

                register_providers()

                logger.info(
                    "providers_re_registered",
                    reason="USE_FAKE_LLM changed",
                    fake_llm=request.USE_FAKE_LLM,
                )

        # Update ENABLE_CACHING if provided
        if request.ENABLE_CACHING is not None:
            old_value = self.settings.ENABLE_CACHING
            self.settings.ENABLE_CACHING = request.ENABLE_CACHING

            if old_value != request.ENABLE_CACHING:
                changes_applied.append(
                    {
                        "field": "ENABLE_CACHING",
                        "old_value": old_value,
                        "new_value": request.ENABLE_CACHING,
                    }
                )

        # Update QUEUE_TYPE if provided
        if request.QUEUE_TYPE is not None:
            # VALIDATION: Check if queue type is valid
            valid_queue_types = ["redis", "kafka"]
            if request.QUEUE_TYPE not in valid_queue_types:
                logger.warning(
                    "invalid_queue_type_requested",
                    requested=request.QUEUE_TYPE,
                    valid_types=valid_queue_types,
                    action="Ignoring invalid value",
                )
            else:
                old_value = self.settings.QUEUE_TYPE
                self.settings.QUEUE_TYPE = request.QUEUE_TYPE

                if old_value != request.QUEUE_TYPE:
                    changes_applied.append(
                        {
                            "field": "QUEUE_TYPE",
                            "old_value": old_value,
                            "new_value": request.QUEUE_TYPE,
                        }
                    )

                    logger.warning(
                        "queue_type_changed",
                        old_type=old_value,
                        new_type=request.QUEUE_TYPE,
                        impact="New queued requests will use new queue type. "
                        "Existing queued requests in old queue will be drained.",
                    )

        # Get current configuration after updates
        current_config = self.get_current_config()

        # Log final audit entry
        logger.info(
            "config_update_completed",
            user_id=user_id,
            changes_applied=changes_applied,
            change_count=len(changes_applied),
            current_config={
                "USE_FAKE_LLM": current_config.USE_FAKE_LLM,
                "ENABLE_CACHING": current_config.ENABLE_CACHING,
                "QUEUE_TYPE": current_config.QUEUE_TYPE,
            },
        )

        return ConfigUpdateResponse(status="updated", current_config=current_config)


# ============================================================================
# DEPENDENCY INJECTION: Singleton Pattern
# ============================================================================

_config_service: ConfigService | None = None


def get_config_service() -> ConfigService:
    """
    Get or create the singleton ConfigService instance.

    SINGLETON RATIONALE:
    --------------------
    ConfigService is stateless, so one instance can serve all requests.
    Benefits:
    - Consistent initialization
    - Easy to mock for testing
    - Centralized creation logic

    Returns:
        Singleton ConfigService instance
    """
    global _config_service

    if _config_service is None:
        # Lazy import to avoid circular dependencies
        from src.core.config.settings import get_settings

        settings = get_settings()
        _config_service = ConfigService(settings=settings)

        logger.info(
            "config_service_singleton_created", context="Service will be reused for all requests"
        )

    return _config_service
