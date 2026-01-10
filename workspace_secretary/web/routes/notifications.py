from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
from typing import Optional

from workspace_secretary.web import database as db
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Track last check time per session (in production, use Redis or DB)
_last_check: dict[str, datetime] = {}


@router.get("/api/notifications/check")
async def check_notifications(
    request: Request, session: Session = Depends(require_auth)
):
    """Check for new priority emails since last check."""
    session_id = request.cookies.get("session_id", "default")
    last_check = _last_check.get(session_id)
    now = datetime.now()

    # Update last check time
    _last_check[session_id] = now

    if last_check is None:
        # First check - don't flood with notifications
        return JSONResponse(
            {
                "new_emails": [],
                "count": 0,
            }
        )

    # Get new priority emails since last check
    new_emails = db.get_new_priority_emails(since=last_check)

    return JSONResponse(
        {
            "new_emails": [
                {
                    "uid": e["uid"],
                    "folder": e.get("folder", "INBOX"),
                    "from": e.get("from_addr", "Unknown"),
                    "subject": e.get("subject", "(no subject)"),
                    "preview": (e.get("preview") or "")[:100],
                    "date": e.get("date").isoformat() if e.get("date") else None,
                }
                for e in new_emails
            ],
            "count": len(new_emails),
        }
    )


@router.post("/api/notifications/subscribe")
async def subscribe_notifications(
    request: Request, session: Session = Depends(require_auth)
):
    """Register push notification subscription (for future PWA support)."""
    # Placeholder for Web Push API integration
    data = await request.json()
    # In production: store subscription in database
    return JSONResponse({"status": "subscribed"})


@router.get("/api/notifications/settings")
async def get_notification_settings(
    request: Request, session: Session = Depends(require_auth)
):
    """Get notification settings."""
    # In production: load from user preferences
    return JSONResponse(
        {
            "enabled": True,
            "sound": True,
            "priority_only": True,
            "check_interval": 30,  # seconds
        }
    )


@router.post("/api/notifications/settings")
async def update_notification_settings(
    request: Request, session: Session = Depends(require_auth)
):
    """Update notification settings."""
    data = await request.json()
    # In production: save to user preferences
    return JSONResponse({"status": "updated"})
