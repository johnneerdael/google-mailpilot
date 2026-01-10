from fastapi import APIRouter, Request, Query, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import json

from workspace_secretary.web import engine_client as engine
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_view(
    request: Request,
    week_offset: int = Query(0),
    session: Session = Depends(require_auth),
):
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=7)

    time_min = week_start.strftime("%Y-%m-%dT00:00:00Z")
    time_max = week_end.strftime("%Y-%m-%dT23:59:59Z")

    try:
        events_response = await engine.get_calendar_events(time_min, time_max)
        events = events_response.get("events", [])
    except Exception:
        events = []

    try:
        freebusy_response = await engine.freebusy_query(time_min, time_max)
        busy_slots = (
            freebusy_response.get("calendars", {}).get("primary", {}).get("busy", [])
        )
    except Exception:
        busy_slots = []

    days = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_events = [
            e
            for e in events
            if e.get("start", {})
            .get("dateTime", "")
            .startswith(day.strftime("%Y-%m-%d"))
        ]
        days.append(
            {
                "date": day,
                "name": day.strftime("%A"),
                "short": day.strftime("%b %d"),
                "events": day_events,
                "is_today": day.date() == now.date(),
            }
        )

    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "days": days,
            "week_start": week_start,
            "week_end": week_end,
            "week_offset": week_offset,
            "busy_slots": busy_slots,
        },
    )


@router.get("/calendar/availability", response_class=HTMLResponse)
async def availability_widget(
    request: Request,
    days: int = Query(7),
    session: Session = Depends(require_auth),
):
    now = datetime.now()
    time_min = now.strftime("%Y-%m-%dT00:00:00Z")
    time_max = (now + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59Z")

    try:
        freebusy_response = await engine.freebusy_query(time_min, time_max)
        busy_slots = (
            freebusy_response.get("calendars", {}).get("primary", {}).get("busy", [])
        )
    except Exception:
        busy_slots = []

    return templates.TemplateResponse(
        "partials/availability_widget.html",
        {
            "request": request,
            "busy_slots": busy_slots,
            "days": days,
        },
    )


@router.post("/api/calendar/event")
async def create_event(
    summary: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    add_meet: bool = Form(False),
    session: Session = Depends(require_auth),
):
    try:
        attendee_list = [a.strip() for a in attendees.split(",")] if attendees else None
        result = await engine.create_calendar_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description or None,
            location=location or None,
            attendees=attendee_list,
            add_meet=add_meet,
        )
        return JSONResponse(
            {"success": True, "message": "Event created", "event": result}
        )
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/calendar/respond/{event_id}")
async def respond_to_event(
    event_id: str,
    response: str = Query(...),
    session: Session = Depends(require_auth),
):
    if response not in ("accepted", "declined", "tentative"):
        return JSONResponse(
            {"success": False, "error": "Invalid response"}, status_code=400
        )

    try:
        result = await engine.respond_to_invite(event_id, response)
        return JSONResponse({"success": True, "message": f"Response: {response}"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
