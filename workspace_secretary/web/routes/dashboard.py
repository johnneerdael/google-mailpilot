from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime, timedelta

from workspace_secretary.web import database as db
from workspace_secretary.web import engine_client as engine
from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.routes.analysis import analyze_signals, compute_priority
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()


@router.get("/dashboard")
async def dashboard_redirect(session: Session = Depends(require_auth)):
    return RedirectResponse(url="/", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(require_auth)):
    unread_emails = db.get_inbox_emails("INBOX", limit=50, offset=0, unread_only=True)

    priority_emails = []
    for email in unread_emails[:20]:
        signals = analyze_signals(email)
        priority, reason = compute_priority(signals)
        if priority in ("high", "medium"):
            priority_emails.append(
                {
                    **email,
                    "priority": priority,
                    "priority_reason": reason,
                    "signals": signals,
                }
            )

    priority_emails = sorted(
        priority_emails,
        key=lambda x: (0 if x["priority"] == "high" else 1, x.get("date", "")),
        reverse=True,
    )[:10]

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_end = now.replace(hour=23, minute=59, second=59).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        events_response = await engine.get_calendar_events(today_start, today_end)
        today_events = events_response.get("events", [])
    except Exception:
        today_events = []

    upcoming_events = []
    for event in today_events:
        start = event.get("start", {}).get("dateTime", "")
        if start:
            try:
                event_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
                if event_time.replace(tzinfo=None) >= now:
                    upcoming_events.append(event)
            except ValueError:
                upcoming_events.append(event)
    upcoming_events = upcoming_events[:5]

    stats = {
        "unread_count": len(unread_emails),
        "priority_count": len([e for e in priority_emails if e["priority"] == "high"]),
        "meetings_today": len(today_events),
    }

    return templates.TemplateResponse(
        "dashboard.html",
        get_template_context(
            request,
            priority_emails=priority_emails,
            upcoming_events=upcoming_events,
            stats=stats,
            now=now,
        ),
    )


@router.get("/api/stats", response_class=HTMLResponse)
async def get_stats(request: Request, session: Session = Depends(require_auth)):
    unread_emails = db.get_inbox_emails("INBOX", limit=100, offset=0, unread_only=True)

    high_priority = 0
    for email in unread_emails[:30]:
        signals = analyze_signals(email)
        priority, _ = compute_priority(signals)
        if priority == "high":
            high_priority += 1

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_end = now.replace(hour=23, minute=59, second=59).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        events_response = await engine.get_calendar_events(today_start, today_end)
        meetings_today = len(events_response.get("events", []))
    except Exception:
        meetings_today = 0

    return templates.TemplateResponse(
        "partials/stats_badges.html",
        get_template_context(
            request,
            unread_count=len(unread_emails),
            priority_count=high_priority,
            meetings_today=meetings_today,
        ),
    )
