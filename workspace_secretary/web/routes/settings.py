"""Settings routes for user preferences."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from workspace_secretary.web import templates, get_template_context, get_web_config
from workspace_secretary.web.auth import require_auth, Session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


class IdentitySettingsRequest(BaseModel):
    email: str
    full_name: str = ""
    aliases: list[str] = []


class AISettingsRequest(BaseModel):
    base_url: str = ""
    api_format: str = ""
    model: str = ""
    token_limit: int | None = None
    api_key: str = ""


class UISettingsRequest(BaseModel):
    theme: str
    density: str


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: Session = Depends(require_auth)):
    web_config = get_web_config()

    ctx = get_template_context(
        request,
        page="settings",
        web_config=web_config,
    )
    return templates.TemplateResponse("settings.html", ctx)


@router.get("/settings/vips", response_class=HTMLResponse)
async def vips_partial(request: Request, session: Session = Depends(require_auth)):
    from workspace_secretary.config import load_config

    config = load_config()
    vips = []
    if config:
        vips = getattr(config, "vip_senders", []) or []

    return templates.TemplateResponse(
        "partials/settings_vips.html",
        {"request": request, "vips": vips},
    )


@router.get("/settings/working-hours", response_class=HTMLResponse)
async def working_hours_partial(
    request: Request, session: Session = Depends(require_auth)
):
    from workspace_secretary.config import load_config

    config = load_config()
    working_hours = {
        "start": "09:00",
        "end": "18:00",
        "workdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "timezone": "UTC",
    }

    if config and hasattr(config, "working_hours") and config.working_hours:
        wh = config.working_hours
        working_hours["start"] = getattr(wh, "start", "09:00")
        working_hours["end"] = getattr(wh, "end", "18:00")
        working_hours["workdays"] = getattr(wh, "workdays", working_hours["workdays"])
        working_hours["timezone"] = getattr(wh, "timezone", "UTC")

    return templates.TemplateResponse(
        "partials/settings_working_hours.html",
        {"request": request, "working_hours": working_hours},
    )


@router.get("/settings/identity", response_class=HTMLResponse)
async def identity_partial(request: Request, session: Session = Depends(require_auth)):
    from workspace_secretary.config import load_config

    config = load_config()
    identity = {
        "email": "",
        "full_name": "",
        "aliases": [],
    }

    if config and config.identity:
        identity["email"] = config.identity.email or ""
        identity["full_name"] = config.identity.full_name or ""
        identity["aliases"] = config.identity.aliases or []

    return templates.TemplateResponse(
        "partials/settings_identity.html",
        {"request": request, "identity": identity},
    )


@router.get("/settings/ai", response_class=HTMLResponse)
async def ai_partial(request: Request, session: Session = Depends(require_auth)):
    web_config = get_web_config()

    ai_config = {
        "configured": False,
        "base_url": "",
        "model": "",
        "api_format": "",
    }

    if web_config and web_config.agent:
        ai_config["configured"] = bool(web_config.agent.api_key)
        ai_config["base_url"] = web_config.agent.base_url or ""
        ai_config["model"] = web_config.agent.model or ""
        ai_config["api_format"] = (
            web_config.agent.api_format.value if web_config.agent.api_format else ""
        )

    return templates.TemplateResponse(
        "partials/settings_ai.html",
        {"request": request, "ai_config": ai_config},
    )


@router.get("/settings/auth", response_class=HTMLResponse)
async def auth_partial(request: Request, session: Session = Depends(require_auth)):
    web_config = get_web_config()

    auth_info = {
        "method": "none",
        "session_expiry": 24,
    }

    if web_config and web_config.auth:
        auth_info["method"] = (
            web_config.auth.method.value if web_config.auth.method else "none"
        )
        auth_info["session_expiry"] = web_config.auth.session_expiry_hours or 24

    return templates.TemplateResponse(
        "partials/settings_auth.html",
        {"request": request, "auth_info": auth_info, "session": session},
    )


@router.post("/api/settings/identity")
async def update_identity_settings(
    payload: IdentitySettingsRequest,
    session: Session = Depends(require_auth),
):
    from workspace_secretary.config import UserIdentityConfig, load_config, save_config

    config = load_config(config_path="config/config.yaml")
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")

    config.identity = UserIdentityConfig(
        email=payload.email,
        full_name=payload.full_name,
        aliases=payload.aliases,
    )

    save_config(config, config_path="config/config.yaml")
    return {"status": "ok"}


@router.post("/api/settings/ai")
async def update_ai_settings(
    payload: AISettingsRequest,
    session: Session = Depends(require_auth),
):
    from workspace_secretary.config import (
        WebAgentConfig,
        WebApiFormat,
        load_config,
        save_config,
    )

    config = load_config(config_path="config/config.yaml")
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")

    if not config.web:
        raise HTTPException(status_code=500, detail="Web config not available")

    agent = config.web.agent or WebAgentConfig()

    if payload.base_url:
        agent.base_url = payload.base_url
    if payload.api_format:
        agent.api_format = WebApiFormat.from_string(payload.api_format)
    if payload.model:
        agent.model = payload.model
    if payload.token_limit is not None:
        agent.token_limit = payload.token_limit
    if payload.api_key:
        agent.api_key = payload.api_key

    config.web.agent = agent

    save_config(config, config_path="config/config.yaml")
    return {"status": "ok"}


@router.put("/api/settings/ui")
async def update_ui_settings(
    payload: UISettingsRequest,
    session: Session = Depends(require_auth),
):
    theme = payload.theme
    density = payload.density

    allowed_themes = {"light", "dark", "system"}
    allowed_density = {"compact", "default", "relaxed"}

    if theme not in allowed_themes:
        raise HTTPException(status_code=400, detail="Invalid theme")
    if density not in allowed_density:
        raise HTTPException(status_code=400, detail="Invalid density")

    from workspace_secretary.web.database import get_pool

    prefs_json = {"theme": theme, "density": density}

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, prefs_json, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET prefs_json = EXCLUDED.prefs_json, updated_at = NOW()
                """,
                (session.user_id, json.dumps(prefs_json)),
            )
        conn.commit()

    return {"status": "ok"}
