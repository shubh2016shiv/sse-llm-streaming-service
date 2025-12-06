"""
Security Headers Middleware - Educational Documentation
========================================================

WHAT ARE SECURITY HEADERS?
---------------------------
Security headers are HTTP response headers that tell browsers how to behave
when handling your site's content. They protect against common web vulnerabilities:

1. XSS (Cross-Site Scripting)
2. Clickjacking
3. MIME-type sniffing
4. Man-in-the-middle attacks
5. Information leakage

WHY ADD SECURITY HEADERS?
--------------------------
Even if your application code is secure, browsers need guidance on:
- What content to trust
- How to handle iframes
- Whether to enforce HTTPS
- What information to share with other sites

Adding security headers is a defense-in-depth strategy that protects users
even if vulnerabilities exist in your code.

COMMON SECURITY HEADERS:
------------------------
1. X-Content-Type-Options: Prevent MIME-type sniffing
2. X-Frame-Options: Prevent clickjacking
3. X-XSS-Protection: Enable browser XSS filters (legacy)
4. Strict-Transport-Security (HSTS): Enforce HTTPS
5. Content-Security-Policy (CSP): Control resource loading
6. Referrer-Policy: Control referrer information
7. Permissions-Policy: Control browser features

This module implements security headers middleware for web application hardening.
"""

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# SECURITY HEADERS CONFIGURATION
# ============================================================================


class SecurityHeadersConfig:
    """
    Configuration for security headers.

    SECURITY HEADER EXPLANATIONS:
    -----------------------------
    Each header serves a specific security purpose. This configuration
    provides sensible defaults that work for most applications.

    You can customize these based on your application's needs.
    """

    # X-Content-Type-Options: nosniff
    # --------------------------------
    # Prevents browsers from MIME-sniffing (guessing content type).
    # Without this, browsers might execute a JSON file as JavaScript if it
    # "looks like" JavaScript, leading to XSS attacks.
    #
    # Example attack without this header:
    # 1. Attacker uploads "image.jpg" containing JavaScript
    # 2. Browser detects it's actually JavaScript and executes it
    # 3. XSS attack succeeds
    #
    # With "nosniff", browser strictly follows Content-Type header.
    X_CONTENT_TYPE_OPTIONS = "nosniff"

    # X-Frame-Options: DENY
    # ---------------------
    # Prevents your site from being embedded in an iframe.
    # This protects against clickjacking attacks where:
    # 1. Attacker embeds your site in invisible iframe
    # 2. Overlays fake UI on top
    # 3. User thinks they're clicking attacker's site
    # 4. Actually clicking your site (e.g., "Delete Account" button)
    #
    # Options:
    # - DENY: Never allow framing
    # - SAMEORIGIN: Allow framing only from same domain
    # - ALLOW-FROM uri: Allow framing from specific domain (deprecated)
    X_FRAME_OPTIONS = "DENY"

    # X-XSS-Protection: 1; mode=block
    # -------------------------------
    # Enables browser's built-in XSS filter (legacy feature).
    # Modern browsers have better XSS protection via CSP, but this
    # provides defense-in-depth for older browsers.
    #
    # Values:
    # - 0: Disable XSS filter
    # - 1: Enable XSS filter
    # - 1; mode=block: Enable and block page if XSS detected
    #
    # Note: This header is deprecated in favor of CSP, but still useful
    # for supporting older browsers.
    X_XSS_PROTECTION = "1; mode=block"

    # Strict-Transport-Security (HSTS)
    # ---------------------------------
    # Forces browsers to ONLY use HTTPS for your domain.
    # After first visit, browser will:
    # 1. Automatically upgrade HTTP to HTTPS
    # 2. Refuse to connect if certificate is invalid
    # 3. Prevent user from bypassing certificate warnings
    #
    # This prevents man-in-the-middle attacks where attacker:
    # 1. Intercepts HTTP request
    # 2. Serves malicious content
    # 3. Steals credentials
    #
    # Parameters:
    # - max-age=31536000: Remember for 1 year (in seconds)
    # - includeSubDomains: Apply to all subdomains
    # - preload: Allow inclusion in browser HSTS preload list
    #
    # WARNING: Only enable HSTS if your site fully supports HTTPS!
    # Once enabled, users can't access your site over HTTP.
    STRICT_TRANSPORT_SECURITY = "max-age=31536000; includeSubDomains"

    # Content-Security-Policy (CSP)
    # ------------------------------
    # Controls what resources the browser can load.
    # This is the most powerful security header, preventing:
    # - XSS attacks (by controlling script sources)
    # - Data injection attacks
    # - Clickjacking
    # - Mixed content issues
    #
    # Directives:
    # - default-src 'self': Only load resources from same origin by default
    # - script-src 'self': Only execute scripts from same origin
    # - style-src 'self' 'unsafe-inline': Allow same-origin styles + inline styles
    #   (unsafe-inline needed for many frameworks, but reduces security)
    # - img-src 'self' data: https:: Allow images from same origin, data URIs, and HTTPS
    # - font-src 'self': Only load fonts from same origin
    # - connect-src 'self': Only allow AJAX/WebSocket to same origin
    # - frame-ancestors 'none': Don't allow framing (similar to X-Frame-Options)
    #
    # Note: This is a strict policy. You may need to relax it for:
    # - CDNs (add CDN domains to script-src, style-src, etc.)
    # - Analytics (add analytics domains to connect-src)
    # - External images (add domains to img-src)
    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )

    # Referrer-Policy: strict-origin-when-cross-origin
    # -------------------------------------------------
    # Controls how much referrer information is sent with requests.
    # The referrer header tells the destination site where the user came from.
    #
    # This policy means:
    # - Same-origin requests: Send full URL
    # - Cross-origin HTTPS→HTTPS: Send origin only (not full URL)
    # - Cross-origin HTTPS→HTTP: Send nothing (downgrade)
    #
    # This balances privacy (don't leak full URLs) with functionality
    # (analytics can still see traffic sources).
    #
    # Options:
    # - no-referrer: Never send referrer
    # - same-origin: Only send for same-origin requests
    # - strict-origin: Only send origin for HTTPS→HTTPS
    # - strict-origin-when-cross-origin: Recommended balance
    REFERRER_POLICY = "strict-origin-when-cross-origin"

    # Permissions-Policy (formerly Feature-Policy)
    # --------------------------------------------
    # Controls which browser features can be used.
    # This prevents malicious scripts from:
    # - Accessing camera/microphone
    # - Getting geolocation
    # - Using payment APIs
    # - Etc.
    #
    # Format: feature=(allowlist)
    # - (): Disable for everyone
    # - (self): Allow for same origin only
    # - (self "https://example.com"): Allow for self and specific domain
    #
    # This configuration disables potentially dangerous features:
    # - geolocation: Location tracking
    # - microphone: Audio recording
    # - camera: Video recording
    # - payment: Payment APIs
    # - usb: USB device access
    PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=(), payment=(), usb=()"


# ============================================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.

    WHY USE MIDDLEWARE FOR SECURITY HEADERS?
    ----------------------------------------
    Adding headers via middleware ensures:
    1. All responses get security headers (no exceptions)
    2. Centralized configuration (one place to update)
    3. Can't forget to add headers to new endpoints
    4. Consistent security posture across the application

    ALTERNATIVE APPROACHES:
    -----------------------
    You could add headers in each route handler, but:
    - Error-prone (easy to forget)
    - Duplicated code
    - Inconsistent (different routes might use different headers)

    Middleware is the right tool for cross-cutting concerns like security.
    """

    def __init__(self, app, config: SecurityHeadersConfig = None):
        """
        Initialize security headers middleware.

        Args:
            app: The ASGI application (FastAPI app)
            config: Security headers configuration (uses defaults if not provided)
        """
        super().__init__(app)
        self.config = config or SecurityHeadersConfig()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Add security headers to all responses.

        MIDDLEWARE PATTERN:
        -------------------
        This middleware:
        1. Calls the next middleware/handler (doesn't modify request)
        2. Gets the response
        3. Adds security headers to the response
        4. Returns the modified response

        The headers are added AFTER the route handler runs, so they're
        present in all responses (success, error, etc.).

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/handler

        Returns:
            Response: The HTTP response with security headers added
        """
        # Call the next middleware or route handler
        response = await call_next(request)

        # Add security headers to the response
        # These headers tell the browser how to handle the content securely
        response.headers["X-Content-Type-Options"] = self.config.X_CONTENT_TYPE_OPTIONS
        response.headers["X-Frame-Options"] = self.config.X_FRAME_OPTIONS
        response.headers["X-XSS-Protection"] = self.config.X_XSS_PROTECTION
        response.headers["Referrer-Policy"] = self.config.REFERRER_POLICY
        response.headers["Permissions-Policy"] = self.config.PERMISSIONS_POLICY

        # Only add HSTS if the request is over HTTPS
        # Adding HSTS to HTTP responses doesn't make sense and can cause issues
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = self.config.STRICT_TRANSPORT_SECURITY

        # Add CSP header
        # Note: CSP can break functionality if too strict, so test thoroughly
        response.headers["Content-Security-Policy"] = self.config.CONTENT_SECURITY_POLICY

        return response


# ============================================================================
# HELPER FUNCTION FOR APP REGISTRATION
# ============================================================================


def add_security_headers_middleware(app, config: SecurityHeadersConfig = None):
    """
    Add security headers middleware to the FastAPI application.

    USAGE:
    ------
        from src.application.api.middleware.security_headers import add_security_headers_middleware

        app = FastAPI()
        add_security_headers_middleware(app)

    CUSTOMIZATION:
    --------------
    To customize headers:

        from src.application.api.middleware.security_headers import (
            add_security_headers_middleware,
            SecurityHeadersConfig
        )

        config = SecurityHeadersConfig()
        config.X_FRAME_OPTIONS = "SAMEORIGIN"  # Allow same-origin framing
        config.CONTENT_SECURITY_POLICY = "default-src 'self' https://cdn.example.com"

        add_security_headers_middleware(app, config)

    TESTING SECURITY HEADERS:
    -------------------------
    After adding this middleware, test with:

        curl -I https://your-api.com/

    Or use online tools:
    - https://securityheaders.com/
    - https://observatory.mozilla.org/

    Args:
        app: FastAPI application instance
        config: Custom security headers configuration (optional)
    """
    app.add_middleware(SecurityHeadersMiddleware, config=config)
    logger.info("Security headers middleware registered")
