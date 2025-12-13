"""
Base Validator Module

Abstract base class and common validation utilities.

ENTERPRISE PATTERN: Template Method Pattern
--------------------------------------------
The BaseValidator provides common validation infrastructure while
allowing subclasses to implement specific validation logic.
"""

import re
from abc import ABC, abstractmethod
from re import Pattern

from src.application.validators.exceptions import SecurityValidationError, ValidationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class BaseValidator(ABC):
    """
    Abstract base validator with common validation utilities.

    DESIGN PATTERN: Template Method
    --------------------------------
    Provides reusable validation methods that all validators can use:
    - Security checks (XSS, SQL injection, path traversal)
    - Length validation
    - Pattern matching
    - Whitelist/blacklist checking

    Subclasses implement specific validation logic for their domain.
    """

    # Common security patterns (shared across all validators)
    SECURITY_PATTERNS: list[tuple[Pattern, str]] = [
        (
            re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
            "XSS: Script tag detected",
        ),
        (re.compile(r"javascript:", re.IGNORECASE), "XSS: JavaScript protocol detected"),
        (re.compile(r"on\w+\s*=", re.IGNORECASE), "XSS: Event handler detected"),
        (re.compile(r"<\w+[^>]*on\w+\s*=", re.IGNORECASE), "XSS: Inline event handler detected"),
        (re.compile(r";\s*drop\s+table", re.IGNORECASE), "SQL Injection: DROP TABLE detected"),
        (re.compile(r";\s*delete\s+from", re.IGNORECASE), "SQL Injection: DELETE FROM detected"),
        (
            re.compile(r";\s*update\s+\w+\s+set", re.IGNORECASE),
            "SQL Injection: UPDATE SET detected",
        ),
        (re.compile(r"union\s+select", re.IGNORECASE), "SQL Injection: UNION SELECT detected"),
        (re.compile(r"\.\./"), "Path Traversal: ../ detected"),
        (re.compile(r"etc/passwd"), "Path Traversal: /etc/passwd detected"),
        (re.compile(r"etc/shadow"), "Path Traversal: /etc/shadow detected"),
        (re.compile(r"\.\.\\\\"), "Path Traversal: ..\\ detected"),
    ]

    def __init__(self, strict: bool = True):
        """
        Initialize base validator.

        Args:
            strict: If True, fail on any validation error.
                   If False, log warnings but don't raise exceptions.

        ENTERPRISE DECISION: Strict Mode
        ---------------------------------
        Strict mode allows different validation behavior:
        - Production: strict=True (fail fast, security first)
        - Development: strict=False (log warnings, continue)
        - Testing: strict=True (catch validation bugs early)
        """
        self.strict = strict

    def validate_length(
        self,
        value: str,
        field_name: str,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> None:
        """
        Validate string length is within bounds.

        Args:
            value: String to validate
            field_name: Name of the field (for error messages)
            min_length: Minimum allowed length (optional)
            max_length: Maximum allowed length (optional)

        Raises:
            ValidationError: If length is out of bounds

        Example:
            validator.validate_length(query, "query", min_length=1, max_length=10000)
        """
        length = len(value)

        if min_length is not None and length < min_length:
            raise ValidationError(
                f"{field_name} too short (minimum {min_length} characters)",
                field=field_name,
                value=f"length={length}",
            )

        if max_length is not None and length > max_length:
            raise ValidationError(
                f"{field_name} too long (maximum {max_length} characters)",
                field=field_name,
                value=f"length={length}",
            )

    def validate_not_empty(self, value: str, field_name: str) -> None:
        """
        Validate string is not empty or whitespace-only.

        Args:
            value: String to validate
            field_name: Name of the field (for error messages)

        Raises:
            ValidationError: If value is empty or whitespace
        """
        if not value or not value.strip():
            raise ValidationError(f"{field_name} cannot be empty", field=field_name)

    def validate_pattern(
        self, value: str, pattern: str | Pattern, field_name: str, error_message: str | None = None
    ) -> None:
        """
        Validate string matches a regex pattern.

        Args:
            value: String to validate
            pattern: Regex pattern (string or compiled)
            field_name: Name of the field (for error messages)
            error_message: Custom error message (optional)

        Raises:
            ValidationError: If value doesn't match pattern
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        if not pattern.match(value):
            message = error_message or f"{field_name} format is invalid"
            raise ValidationError(message, field=field_name)

    def validate_whitelist(
        self, value: str, allowed_values: set[str], field_name: str, case_sensitive: bool = True
    ) -> None:
        """
        Validate value is in allowed set (whitelist).

        Args:
            value: Value to validate
            allowed_values: Set of allowed values
            field_name: Name of the field (for error messages)
            case_sensitive: Whether comparison is case-sensitive

        Raises:
            ValidationError: If value not in whitelist

        ENTERPRISE PATTERN: Whitelist Validation
        -----------------------------------------
        Whitelist validation is more secure than blacklist:
        - Explicitly allow known-good values
        - Reject everything else by default
        - Prevents bypass via encoding/obfuscation
        """
        check_value = value if case_sensitive else value.lower()
        check_set = allowed_values if case_sensitive else {v.lower() for v in allowed_values}

        if check_value not in check_set:
            raise ValidationError(
                f"Invalid {field_name}: '{value}' not in allowed values",
                field=field_name,
                value=value,
            )

    def check_security_patterns(self, value: str, field_name: str) -> None:
        """
        Check for malicious patterns (XSS, SQL injection, path traversal).

        Args:
            value: String to check
            field_name: Name of the field (for error messages)

        Raises:
            SecurityValidationError: If malicious pattern detected

        ENTERPRISE SECURITY: Defense in Depth
        --------------------------------------
        Multiple layers of security:
        1. Input validation (this method)
        2. Parameterized queries (prevents SQL injection)
        3. Output encoding (prevents XSS)
        4. Content Security Policy (browser-level protection)

        This is the FIRST layer - catch obvious attacks early.
        """
        for pattern, description in self.SECURITY_PATTERNS:
            if pattern.search(value):
                logger.warning(
                    f"Security pattern detected in {field_name}",
                    pattern=description,
                    field=field_name,
                )
                raise SecurityValidationError(
                    f"Potentially malicious content detected: {description}", field=field_name
                )

    @abstractmethod
    def validate(self, **kwargs) -> None:
        """
        Validate input data.

        ABSTRACT METHOD: Subclasses must implement
        -------------------------------------------
        Each validator implements its own validation logic.

        Example:
            class QueryValidator(BaseValidator):
                def validate(self, query: str) -> None:
                    self.validate_not_empty(query, "query")
                    self.validate_length(query, "query", max_length=10000)
                    self.check_security_patterns(query, "query")
        """
        pass
