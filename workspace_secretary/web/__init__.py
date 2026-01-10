"""
Web UI for Gmail Secretary - AI-powered email client.

Provides a human interface to the email system with:
- Inbox view with pagination
- Thread/conversation view
- Semantic search
- AI assistant integration (configurable LLM)
- Authentication (password, OIDC, SAML2)
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pathlib import Path
import logging
from typing import Optional

from workspace_secretary.config import WebConfig

logger = logging.getLogger(__name__)

__all__ = [
    "web_app",
    "templates",
    "init_web_app",
    "get_web_config",
    "get_template_context",
]

web_app = FastAPI(
    title="Secretary Web",
    description="AI-powered email client",
    docs_url="/api/docs",
    redoc_url=None,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

web_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_web_config: Optional[WebConfig] = None


def init_web_app(config: Optional[WebConfig] = None):
    """Initialize web app with configuration."""
    global _web_config
    _web_config = config

    from workspace_secretary.web.auth import init_auth, router as auth_router

    init_auth(config)
    web_app.include_router(auth_router)

    logger.info("Web app initialized")


def get_web_config() -> Optional[WebConfig]:
    """Get current web configuration."""
    return _web_config


def get_template_context(request: Request, **kwargs) -> dict:
    """Build template context with theme and session info."""
    from workspace_secretary.web.auth import get_session

    session = get_session(request)
    theme = "dark"
    if _web_config and _web_config.theme:
        theme = _web_config.theme

    return {
        "request": request,
        "theme": theme,
        "session": session,
        "user_name": session.name if session else None,
        "user_email": session.email if session else None,
        **kwargs,
    }


@web_app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Redirect to dashboard."""
    return RedirectResponse(url="/dashboard")


@web_app.get("/favicon.ico")
async def favicon():
    """Return empty favicon to prevent 404."""
    return Response(content=b"", media_type="image/x-icon")


@web_app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "secretary-web"}
