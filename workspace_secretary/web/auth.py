"""
Authentication middleware for Secretary Web UI.

Supports:
- No auth (development)
- Password auth (single user)
- OIDC (Google, Okta, Auth0, etc.)
- SAML2 (Enterprise SSO)
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRouter

from workspace_secretary.config import (
    WebAuthMethod,
    WebConfig,
    WebOIDCConfig,
    WebSAML2Config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Session cookie name
SESSION_COOKIE = "secretary_session"
CSRF_COOKIE = "secretary_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_MAX_AGE = 86400  # 24 hours default


@dataclass
class Session:
    """User session data."""

    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    created_at: float = 0.0
    expires_at: float = 0.0
    csrf_token: Optional[str] = None

    def is_valid(self) -> bool:
        return time.time() < self.expires_at

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_id": self.user_id,
                "email": self.email,
                "name": self.name,
                "created_at": self.created_at,
                "expires_at": self.expires_at,
                "csrf_token": self.csrf_token,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> "Session":
        d = json.loads(data)
        return cls(
            user_id=d["user_id"],
            email=d.get("email"),
            name=d.get("name"),
            created_at=d.get("created_at", 0.0),
            expires_at=d.get("expires_at", 0.0),
            csrf_token=d.get("csrf_token"),
        )


class AuthManager:
    """Manages authentication for the web UI."""

    def __init__(self, config: Optional[WebConfig] = None):
        self.config = config
        self._oidc_config_cache: Optional[dict] = None
        self._oidc_config_expires: float = 0.0

    @property
    def auth_config(self):
        return self.config.auth if self.config else None

    @property
    def method(self) -> WebAuthMethod:
        if not self.auth_config:
            return WebAuthMethod.NONE
        return self.auth_config.method

    @property
    def session_secret(self) -> bytes:
        if not self.auth_config or not self.auth_config.session_secret:
            # Fallback for development - NOT SECURE
            return b"insecure-dev-secret-do-not-use-in-production"
        return self.auth_config.session_secret.encode()

    @property
    def session_expiry(self) -> int:
        if not self.auth_config:
            return SESSION_MAX_AGE
        return self.auth_config.session_expiry_hours * 3600

    def create_session(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        csrf_token: Optional[str] = None,
    ) -> str:
        """Create a signed session token."""
        now = time.time()
        session = Session(
            user_id=user_id,
            email=email,
            name=name,
            created_at=now,
            expires_at=now + self.session_expiry,
            csrf_token=csrf_token,
        )
        payload = session.to_json()
        signature = hmac.new(
            self.session_secret, payload.encode(), hashlib.sha256
        ).hexdigest()
        token = b64encode(f"{payload}|{signature}".encode()).decode()
        return token

    def verify_session(self, token: str) -> Optional[Session]:
        """Verify and decode a session token."""
        try:
            decoded = b64decode(token.encode()).decode()
            payload, signature = decoded.rsplit("|", 1)
            expected = hmac.new(
                self.session_secret, payload.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                logger.warning("Invalid session signature")
                return None
            session = Session.from_json(payload)
            if not session.is_valid():
                logger.debug("Session expired")
                return None
            return session
        except Exception as e:
            logger.debug(f"Session verification failed: {e}")
            return None

    def verify_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        if not self.auth_config or not self.auth_config.password_hash:
            return False

        stored_hash = self.auth_config.password_hash

        # Support argon2 if available
        if stored_hash.startswith("$argon2"):
            try:
                from argon2 import PasswordHasher
                from argon2.exceptions import VerifyMismatchError

                ph = PasswordHasher()
                try:
                    ph.verify(stored_hash, password)
                    return True
                except VerifyMismatchError:
                    return False
            except ImportError:
                logger.error("argon2-cffi not installed, cannot verify argon2 hash")
                return False

        # Support bcrypt
        if stored_hash.startswith("$2"):
            try:
                import bcrypt

                return bcrypt.checkpw(password.encode(), stored_hash.encode())
            except ImportError:
                logger.error("bcrypt not installed, cannot verify bcrypt hash")
                return False

        # Fallback: SHA-256 (not recommended for production)
        if stored_hash.startswith("sha256:"):
            _, salt, hash_val = stored_hash.split(":")
            computed = hashlib.sha256((salt + password).encode()).hexdigest()
            return hmac.compare_digest(computed, hash_val)

        logger.error(f"Unknown password hash format: {stored_hash[:10]}...")
        return False

    async def get_oidc_config(self) -> dict:
        """Fetch OIDC provider configuration."""
        if not self.auth_config or not self.auth_config.oidc:
            raise ValueError("OIDC not configured")

        # Cache for 1 hour
        if (
            self._oidc_config_cache is not None
            and time.time() < self._oidc_config_expires
        ):
            return self._oidc_config_cache

        oidc = self.auth_config.oidc
        well_known_url = (
            f"{oidc.provider_url.rstrip('/')}/.well-known/openid-configuration"
        )

        async with httpx.AsyncClient() as client:
            resp = await client.get(well_known_url, timeout=10.0)
            resp.raise_for_status()
            self._oidc_config_cache = resp.json()
            self._oidc_config_expires = time.time() + 3600
            return self._oidc_config_cache  # type: ignore[return-value]

    def get_oidc_authorize_url(self, redirect_uri: str, state: str) -> str:
        """Build OIDC authorization URL."""
        if not self.auth_config or not self.auth_config.oidc:
            raise ValueError("OIDC not configured")

        oidc = self.auth_config.oidc

        # For common providers, use standard endpoints
        # In production, fetch from .well-known/openid-configuration
        authorize_endpoint = f"{oidc.provider_url.rstrip('/')}/authorize"

        # Google-specific endpoint
        if "accounts.google.com" in oidc.provider_url:
            authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"

        params = {
            "client_id": oidc.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(oidc.scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{authorize_endpoint}?{urlencode(params)}"

    async def exchange_oidc_code(
        self, code: str, redirect_uri: str
    ) -> tuple[str, Optional[str], Optional[str]]:
        """Exchange authorization code for tokens and user info."""
        if not self.auth_config or not self.auth_config.oidc:
            raise ValueError("OIDC not configured")

        oidc = self.auth_config.oidc

        # Token endpoint
        token_endpoint = f"{oidc.provider_url.rstrip('/')}/token"
        if "accounts.google.com" in oidc.provider_url:
            token_endpoint = "https://oauth2.googleapis.com/token"

        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_resp = await client.post(
                token_endpoint,
                data={
                    "client_id": oidc.client_id,
                    "client_secret": oidc.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=10.0,
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()

            # Get user info
            userinfo_endpoint = f"{oidc.provider_url.rstrip('/')}/userinfo"
            if "accounts.google.com" in oidc.provider_url:
                userinfo_endpoint = "https://openidconnect.googleapis.com/v1/userinfo"

            userinfo_resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=10.0,
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()

            user_id = userinfo.get("sub", userinfo.get("id", "unknown"))
            email = userinfo.get("email")
            name = userinfo.get("name")

            return user_id, email, name


# Global auth manager instance
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Get or create the auth manager."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def init_auth(config: Optional[WebConfig]):
    """Initialize auth with configuration."""
    global _auth_manager
    _auth_manager = AuthManager(config)
    logger.info(f"Auth initialized with method: {_auth_manager.method.value}")


def get_session(request: Request) -> Optional[Session]:
    """Extract and verify session from request."""
    auth_mgr = get_auth_manager()
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return auth_mgr.verify_session(token)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            session = get_session(request)
            if session:
                expected = session.csrf_token or ""
                provided = request.headers.get(CSRF_HEADER) or ""
                if (
                    not expected
                    or not provided
                    or not hmac.compare_digest(provided, expected)
                ):
                    raise HTTPException(
                        status_code=403, detail="CSRF token missing or invalid"
                    )

        return await call_next(request)


async def require_auth(request: Request) -> Session:
    """Dependency that requires authentication."""
    auth_mgr = get_auth_manager()

    # No auth required
    if auth_mgr.method == WebAuthMethod.NONE:
        return Session(user_id="anonymous", email=None, name="Anonymous")

    session = get_session(request)
    if not session:
        # For HTMX requests, return 401 so JS can redirect
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, detail="Authentication required")
        # For regular requests, redirect to login
        raise HTTPException(
            status_code=307,
            headers={"Location": f"/auth/login?next={request.url.path}"},
        )
    return session


# In-memory state storage for OIDC (use Redis in production)
_oidc_states: dict[str, float] = {}


def _generate_state() -> str:
    """Generate and store OIDC state parameter."""
    state = secrets.token_urlsafe(32)
    _oidc_states[state] = time.time() + 600  # Valid for 10 minutes
    # Clean old states
    now = time.time()
    expired = [s for s, exp in _oidc_states.items() if exp < now]
    for s in expired:
        del _oidc_states[s]
    return state


def _verify_state(state: str) -> bool:
    """Verify OIDC state parameter."""
    if state not in _oidc_states:
        return False
    if time.time() > _oidc_states[state]:
        del _oidc_states[state]
        return False
    del _oidc_states[state]
    return True


# =============================================================================
# Auth Routes
# =============================================================================


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """Render login page."""
    from workspace_secretary.web import templates

    auth_mgr = get_auth_manager()

    # No auth required - redirect
    if auth_mgr.method == WebAuthMethod.NONE:
        return RedirectResponse(url=next)

    # Already logged in - redirect
    session = get_session(request)
    if session:
        return RedirectResponse(url=next)

    # OIDC - redirect to provider
    if auth_mgr.method == WebAuthMethod.OIDC:
        state = _generate_state()
        redirect_uri = str(request.url_for("oidc_callback"))
        auth_url = auth_mgr.get_oidc_authorize_url(redirect_uri, state)
        return RedirectResponse(url=auth_url)

    # SAML2 - redirect to IdP
    if auth_mgr.method == WebAuthMethod.SAML2:
        # TODO: Implement SAML2 redirect
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "next": next,
                "method": "saml2",
                "error": "SAML2 not yet implemented",
            },
        )

    # Password auth - show login form
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "next": next,
            "method": "password",
            "error": None,
        },
    )


@router.post("/login")
async def login_submit(request: Request):
    """Handle password login form submission."""
    from workspace_secretary.web import templates

    auth_mgr = get_auth_manager()
    form = await request.form()
    password = form.get("password", "")
    next_url = form.get("next", "/")

    if auth_mgr.verify_password(str(password)):
        csrf_token = secrets.token_urlsafe(32)
        token = auth_mgr.create_session(
            user_id="admin", email=None, name="Admin", csrf_token=csrf_token
        )
        response = RedirectResponse(url=str(next_url), status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=auth_mgr.session_expiry,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            max_age=auth_mgr.session_expiry,
            httponly=False,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response

    # Invalid password
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "next": next_url,
            "method": "password",
            "error": "Invalid password",
        },
        status_code=401,
    )


@router.get("/callback", name="oidc_callback")
async def oidc_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
):
    """Handle OIDC callback."""
    auth_mgr = get_auth_manager()

    if error:
        logger.error(f"OIDC error: {error}")
        return RedirectResponse(url="/auth/login?error=oidc_error")

    if not _verify_state(state):
        logger.error("Invalid OIDC state")
        return RedirectResponse(url="/auth/login?error=invalid_state")

    try:
        redirect_uri = str(request.url_for("oidc_callback"))
        user_id, email, name = await auth_mgr.exchange_oidc_code(code, redirect_uri)

        csrf_token = secrets.token_urlsafe(32)
        token = auth_mgr.create_session(
            user_id=user_id, email=email, name=name, csrf_token=csrf_token
        )
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=auth_mgr.session_expiry,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            max_age=auth_mgr.session_expiry,
            httponly=False,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response
    except Exception as e:
        logger.exception(f"OIDC callback failed: {e}")
        return RedirectResponse(url="/auth/login?error=callback_failed")


@router.get("/logout")
async def logout(request: Request):
    """Log out and clear session."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return response


# =============================================================================
# SAML2 Routes (Placeholder)
# =============================================================================


@router.get("/saml/metadata")
async def saml_metadata(request: Request):
    """Return SAML2 SP metadata."""
    # TODO: Generate SP metadata XML
    return Response(
        content="<EntityDescriptor><!-- TODO --></EntityDescriptor>",
        media_type="application/xml",
    )


@router.post("/saml/acs")
async def saml_acs(request: Request):
    """SAML2 Assertion Consumer Service endpoint."""
    # TODO: Implement SAML2 response handling
    # 1. Parse SAMLResponse from form data
    # 2. Validate signature
    # 3. Extract user attributes
    # 4. Create session
    raise HTTPException(status_code=501, detail="SAML2 not yet implemented")


@router.get("/saml/sls")
async def saml_sls(request: Request):
    """SAML2 Single Logout Service endpoint."""
    # TODO: Implement SAML2 logout
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
