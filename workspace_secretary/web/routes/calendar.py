from fastapi import APIRouter, Request, Query, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from datetime import datetime, timedelta
import json

from workspace_secretary.web import (
    engine_client as engine,
    templates,
    get_template_context,
)
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()


def _get_event_date(event: dict) -> str:
    start = event.get("start", {})
    return start.get("dateTime", start.get("date", ""))[:10]


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_view(
    request: Request,
    view: str = Query("week"),
    week_offset: int = Query(0),
    day_offset: int = Query(0),
    month_offset: int = Query(0),
    session: Session = Depends(require_auth),
):
    now = datetime.now()

    week_start = None
    week_end = None

    if view == "day":
        target_day = now + timedelta(days=day_offset)
        time_min = target_day.strftime("%Y-%m-%dT00:00:00Z")
        time_max = target_day.strftime("%Y-%m-%dT23:59:59Z")
    elif view == "month":
        target_month = now.replace(day=1) + timedelta(days=32 * month_offset)
        target_month = target_month.replace(day=1)
        month_start = target_month
        next_month = (target_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(seconds=1)
        time_min = month_start.strftime("%Y-%m-%dT00:00:00Z")
        time_max = month_end.strftime("%Y-%m-%dT23:59:59Z")
    elif view == "agenda":
        time_min = now.strftime("%Y-%m-%dT00:00:00Z")
        time_max = (now + timedelta(days=30)).strftime("%Y-%m-%dT23:59:59Z")
    else:
        week_start = now - timedelta(days=now.weekday()) + timedelta(weeks=week_offset)
        week_end = week_start + timedelta(days=7)
        time_min = week_start.strftime("%Y-%m-%dT00:00:00Z")
        time_max = week_end.strftime("%Y-%m-%dT23:59:59Z")

    engine_error = None
    try:
        events_response = await engine.get_calendar_events(time_min, time_max)
        events = events_response.get("events", [])
    except Exception as e:
        events = []
        engine_error = f"Calendar service unavailable: {str(e)}"

    try:
        freebusy_response = await engine.freebusy_query(time_min, time_max)
        busy_slots = (
            freebusy_response.get("freebusy", {})
            .get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )
    except Exception as e:
        busy_slots = []
        if not engine_error:
            engine_error = f"Calendar service unavailable: {str(e)}"

    context = get_template_context(
        request,
        view=view,
        events=events,
        busy_slots=busy_slots,
        now=now,
        engine_error=engine_error,
    )

    if view == "day":
        target_day = now + timedelta(days=day_offset)
        target_date_str = target_day.strftime("%Y-%m-%d")
        day_events = [e for e in events if _get_event_date(e) == target_date_str]
        context.update(
            {
                "target_day": target_day,
                "day_offset": day_offset,
                "day_events": day_events,
            }
        )
    elif view == "month":
        target_month = now.replace(day=1) + timedelta(days=32 * month_offset)
        target_month = target_month.replace(day=1)
        month_start = target_month
        month_name = target_month.strftime("%B %Y")

        first_weekday = month_start.weekday()
        calendar_start = month_start - timedelta(days=first_weekday)

        weeks = []
        current = calendar_start
        for week in range(6):
            week_days = []
            for day in range(7):
                day_date = current + timedelta(days=week * 7 + day)
                day_date_str = day_date.strftime("%Y-%m-%d")
                day_events = [e for e in events if _get_event_date(e) == day_date_str]
                week_days.append(
                    {
                        "date": day_date,
                        "day_num": day_date.day,
                        "is_current_month": day_date.month == target_month.month,
                        "is_today": day_date.date() == now.date(),
                        "events": day_events,
                    }
                )
            weeks.append(week_days)

        context.update(
            {
                "month_offset": month_offset,
                "month_name": month_name,
                "weeks": weeks,
            }
        )
    elif view == "agenda":
        sorted_events = sorted(events, key=_get_event_date)
        grouped_events = {}
        for event in sorted_events:
            event_date = _get_event_date(event)
            if event_date not in grouped_events:
                grouped_events[event_date] = []
            grouped_events[event_date].append(event)

        context.update(
            {
                "grouped_events": grouped_events,
            }
        )
    else:
        week_start = now - timedelta(days=now.weekday()) + timedelta(weeks=week_offset)
        week_end = week_start + timedelta(days=7)
        days = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            day_events = [e for e in events if _get_event_date(e) == day_str]
            days.append(
                {
                    "date": day,
                    "name": day.strftime("%A"),
                    "short": day.strftime("%b %d"),
                    "events": day_events,
                    "is_today": day.date() == now.date(),
                }
            )

        context.update(
            {
                "days": days,
                "week_start": week_start,
                "week_end": week_end,
                "week_offset": week_offset,
            }
        )

    return templates.TemplateResponse("calendar.html", context)


@router.get("/calendar/find-time", response_class=HTMLResponse)
async def find_time_view(
    request: Request,
    session: Session = Depends(require_auth),
):
    return templates.TemplateResponse(
        "calendar_find_time.html",
        get_template_context(request),
    )


@router.post("/api/calendar/find-time", response_class=JSONResponse)
async def find_time_slots(
    request: Request,
    duration: int = Form(30),
    attendees: str = Form(""),
    date_range_start: str = Form(...),
    date_range_end: str = Form(...),
    timezone: str = Form("Europe/Amsterdam"),
    session: Session = Depends(require_auth),
):
    try:
        attendee_list = [a.strip() for a in attendees.split(",") if a.strip()]

        start_dt = datetime.fromisoformat(date_range_start)
        end_dt = datetime.fromisoformat(date_range_end)

        time_min = start_dt.strftime("%Y-%m-%dT00:00:00Z")
        time_max = end_dt.strftime("%Y-%m-%dT23:59:59Z")

        my_events = await engine.get_calendar_events(time_min, time_max)
        my_busy = my_events.get("events", [])

        freebusy_response = await engine.freebusy_query(time_min, time_max)
        busy_slots = (
            freebusy_response.get("freebusy", {})
            .get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )

        slots = []
        current = start_dt.replace(hour=11, minute=0, second=0, microsecond=0)
        end_time = end_dt.replace(hour=22, minute=0, second=0, microsecond=0)

        while current < end_time:
            slot_end = current + timedelta(minutes=duration)

            if current.hour >= 11 and slot_end.hour <= 22:
                is_busy = False
                for event in my_busy:
                    event_start = event.get("start", {}).get("dateTime", "")
                    event_end = event.get("end", {}).get("dateTime", "")
                    if event_start and event_end:
                        evt_start = datetime.fromisoformat(
                            event_start.replace("Z", "+00:00")
                        )
                        evt_end = datetime.fromisoformat(
                            event_end.replace("Z", "+00:00")
                        )

                        if not (slot_end <= evt_start or current >= evt_end):
                            is_busy = True
                            break

                if not is_busy:
                    slots.append(
                        {
                            "start": current.isoformat(),
                            "end": slot_end.isoformat(),
                            "display": f"{current.strftime('%a %b %d, %H:%M')} - {slot_end.strftime('%H:%M')}",
                            "date": current.strftime("%Y-%m-%d"),
                            "conflicts": 0,
                        }
                    )

            current += timedelta(minutes=30)
            if current.hour >= 22:
                current = (current + timedelta(days=1)).replace(hour=11, minute=0)

        return JSONResponse(
            {
                "success": True,
                "slots": slots[:20],
                "total": len(slots),
            }
        )
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=400,
        )


@router.post("/api/calendar/propose-times", response_class=JSONResponse)
async def propose_alternative_times(
    request: Request,
    event_id: str = Form(...),
    proposed_times: str = Form(...),
    message: str = Form(""),
    session: Session = Depends(require_auth),
):
    try:
        times = json.loads(proposed_times)

        return JSONResponse(
            {
                "success": True,
                "message": "Alternative times proposed successfully",
                "proposed_times": times,
            }
        )
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=400,
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
            freebusy_response.get("freebusy", {})
            .get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )
    except Exception:
        busy_slots = []

    return templates.TemplateResponse(
        "partials/availability_widget.html",
        get_template_context(
            request,
            busy_slots=busy_slots,
            days=days,
        ),
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
        if result.get("status") == "error":
            return JSONResponse(
                {"success": False, "error": result.get("message", "Unknown error")},
                status_code=500,
            )
        return JSONResponse({"success": True, "message": f"Response: {response}"})
    except HTTPException as e:
        return JSONResponse(
            {"success": False, "error": e.detail or "Service unavailable"},
            status_code=e.status_code,
        )
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/book/{link_id}", response_class=HTMLResponse)
async def public_booking_page(
    request: Request,
    link_id: str,
):
    return templates.TemplateResponse(
        "calendar_booking.html",
        get_template_context(
            request,
            link_id=link_id,
        ),
    )


@router.get("/api/calendar/booking-slots")
async def get_booking_slots(
    link_id: str = Query(...),
):
    try:
        now = datetime.now()
        start_dt = now
        end_dt = now + timedelta(days=14)

        time_min = start_dt.strftime("%Y-%m-%dT00:00:00Z")
        time_max = end_dt.strftime("%Y-%m-%dT23:59:59Z")

        events_response = await engine.get_calendar_events(time_min, time_max)
        busy_events = events_response.get("events", [])

        slots = []
        current = start_dt.replace(hour=11, minute=0, second=0, microsecond=0)
        if current < start_dt:
            current += timedelta(days=1)

        while current < end_dt:
            if current.weekday() < 5:
                slot_end = current + timedelta(minutes=30)

                if current.hour >= 11 and slot_end.hour <= 22:
                    is_busy = False
                    for event in busy_events:
                        event_start = event.get("start", {}).get("dateTime", "")
                        event_end = event.get("end", {}).get("dateTime", "")
                        if event_start and event_end:
                            evt_start = datetime.fromisoformat(
                                event_start.replace("Z", "+00:00")
                            )
                            evt_end = datetime.fromisoformat(
                                event_end.replace("Z", "+00:00")
                            )

                            if not (slot_end <= evt_start or current >= evt_end):
                                is_busy = True
                                break

                    if not is_busy and current > now:
                        slots.append(
                            {
                                "start": current.isoformat(),
                                "end": slot_end.isoformat(),
                                "display": f"{current.strftime('%A, %B %d at %H:%M')}",
                            }
                        )

            current += timedelta(minutes=30)
            if current.hour >= 22:
                current = (current + timedelta(days=1)).replace(hour=11, minute=0)

        return JSONResponse(
            {
                "success": True,
                "slots": slots[:20],
            }
        )
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=400,
        )


@router.post("/api/calendar/book")
async def book_meeting(
    link_id: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    notes: str = Form(""),
    slot_start: str = Form(...),
    slot_end: str = Form(...),
):
    try:
        summary = f"Meeting with {name}"
        description = f"Booked via scheduling link\n\nAttendee: {name} ({email})"
        if notes:
            description += f"\n\nNotes: {notes}"

        result = await engine.create_calendar_event(
            summary=summary,
            start_time=slot_start,
            end_time=slot_end,
            description=description,
            attendees=[email],
            add_meet=True,
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Meeting booked successfully",
                "event": result,
            }
        )
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=500,
        )
