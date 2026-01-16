from fastapi import APIRouter, Request, Query, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import logging

from workspace_secretary.web import (
    engine_client as engine,
    templates,
    get_template_context,
)
from workspace_secretary.web.auth import require_auth, Session
from workspace_secretary.web import database as db

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_event_date(event: dict) -> str:
    start = event.get("start", {})
    return start.get("dateTime", start.get("date", ""))[:10]


def _event_calendar_id(event: dict[str, Any]) -> Optional[str]:
    return (
        event.get("calendarId") or event.get("calendar_id") or event.get("calendarID")
    )


def _advance_to_next_day(current: datetime, start_hour: int) -> datetime:
    return (current + timedelta(days=1)).replace(
        hour=start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )


def _parse_event_boundary(value: str, target_tz: ZoneInfo) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(target_tz)
    except Exception:
        return None


def _get_timezone(tz_name: Optional[str]) -> ZoneInfo:
    name = tz_name or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone %s for booking link; defaulting to UTC", name)
    except Exception:
        logger.warning("Failed to load timezone %s; defaulting to UTC", name)
    return ZoneInfo("UTC")


def _parse_event_datetime(
    value: Optional[str], target_tz: ZoneInfo
) -> Optional[datetime]:
    if not value:
        return None
    normalized = value
    if "T" not in normalized:
        normalized = f"{normalized}T00:00:00"
    normalized = normalized.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=target_tz)
    return dt.astimezone(target_tz)


def _build_busy_windows(
    events: list[dict[str, Any]], booking_tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    for event in events:
        start_info = event.get("start") or {}
        end_info = event.get("end") or {}
        start_dt = _parse_event_datetime(
            start_info.get("dateTime") or start_info.get("date"), booking_tz
        )
        end_dt = _parse_event_datetime(
            end_info.get("dateTime") or end_info.get("date"), booking_tz
        )
        if not start_dt or not end_dt:
            continue
        windows.append((start_dt, end_dt))
    return windows


def _generate_booking_slots(
    booking_tz: ZoneInfo,
    busy_windows: list[tuple[datetime, datetime]],
    start_dt: datetime,
    end_dt: datetime,
    duration_minutes: int,
    start_hour: int,
    end_hour: int,
) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    current = start_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if current < start_dt:
        current = _advance_to_next_day(current, start_hour)

    while current < end_dt:
        if current.weekday() < 5:
            slot_end = current + timedelta(minutes=duration_minutes)
            day_end = current.replace(hour=end_hour, minute=0, second=0, microsecond=0)
            if slot_end <= day_end and slot_end.date() == current.date():
                is_busy = False
                for busy_start, busy_end in busy_windows:
                    if not (slot_end <= busy_start or current >= busy_end):
                        is_busy = True
                        break
                if not is_busy and current > start_dt:
                    slots.append(
                        {
                            "start": current.astimezone(ZoneInfo("UTC")).isoformat(),
                            "end": slot_end.astimezone(ZoneInfo("UTC")).isoformat(),
                            "display": current.strftime("%A, %B %d at %H:%M"),
                        }
                    )
        current += timedelta(minutes=duration_minutes)
        if current.hour > end_hour or (current.hour == end_hour and current.minute > 0):
            current = _advance_to_next_day(current, start_hour)
    return slots


def _get_booking_link_context(
    link_id: str,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Fetch booking link along with an error descriptor if invalid/inactive."""

    link = db.get_booking_link(link_id)
    if not link:
        return None, {"status": 404, "detail": "Booking link not found"}
    if not link.get("is_active", True):
        return None, {"status": 410, "detail": "Booking link is inactive"}
    return link, None


def _require_booking_link(link_id: str) -> dict[str, Any]:
    link, error = _get_booking_link_context(link_id)
    if error:
        raise HTTPException(status_code=error["status"], detail=error["detail"])
    assert link is not None  # For type-checkers
    return link


@router.get("/api/calendar/conference-solutions")
async def get_conference_solutions(
    calendar_id: str = "primary",
    session: Session = Depends(require_auth),
):
    """Get available conference solutions for creating video meetings."""
    try:
        response = await engine.get_conference_solutions(calendar_id)
        return response
    except Exception as e:
        logger.exception("Failed to fetch conference solutions")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch conference solutions: {str(e)}",
        )


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
    selection_state = {
        "selected_ids": ["primary"],
        "available_ids": ["primary"],
        "states": [],
    }
    events: list[dict] = []

    try:
        selection_state, events = db.get_user_calendar_events_with_state(
            session.user_id, time_min, time_max
        )
    except Exception as e:
        logger.error(
            f"Failed to fetch calendar events from database: {e}", exc_info=True
        )
        engine_error = f"Calendar service unavailable: {str(e)}"

    busy_slots = []
    try:
        freebusy_response = await engine.freebusy_query(
            time_min, time_max, selection_state["selected_ids"]
        )
        busy_by_calendar = (
            freebusy_response.get("freebusy", {}).get("calendars", {}) or {}
        )
        for cid in selection_state["selected_ids"]:
            busy_slots.extend(busy_by_calendar.get(cid, {}).get("busy", []))
    except Exception as e:
        logger.error(f"Failed to fetch freebusy data from engine: {e}", exc_info=True)
        if not engine_error:
            engine_error = f"Calendar service unavailable: {str(e)}"

    calendar_options: list[dict] = []
    try:
        calendars_response = await engine.list_calendars()
        if calendars_response.get("status") == "ok":
            calendar_options = calendars_response.get("calendars", []) or []
    except Exception as e:
        logger.warning("Failed to load calendar list: %s", e)

    filtered_options = []
    available = set(selection_state["available_ids"])
    for cal in calendar_options:
        cal_id = cal.get("id") or cal.get("calendarId")
        if not cal_id:
            continue
        status_info = next(
            (
                state
                for state in selection_state["states"]
                if state.get("calendar_id") == cal_id
            ),
            {},
        )
        last_sync_dt = status_info.get("last_incremental_sync_at") or status_info.get(
            "last_full_sync_at"
        )
        cal_copy = {
            **cal,
            "id": cal_id,
            "selected": cal_id in selection_state["selected_ids"],
            "sync_status": status_info.get("status"),
            "last_sync": last_sync_dt.isoformat() if last_sync_dt else None,
        }
        if cal_id in available:
            filtered_options.append(cal_copy)
        else:
            cal_copy["available"] = False
            filtered_options.append(cal_copy)
    calendar_options = filtered_options

    if not calendar_options:
        calendar_options = [
            {
                "id": cid,
                "summary": cid,
                "selected": cid in selection_state["selected_ids"],
                "primary": cid == "primary",
            }
            for cid in selection_state["available_ids"]
        ]

    context = get_template_context(
        request,
        view=view,
        events=events,
        busy_slots=busy_slots,
        now=now,
        engine_error=engine_error,
        calendar_options=calendar_options,
        selected_calendar_ids=selection_state["selected_ids"],
        available_calendar_ids=selection_state["available_ids"],
        calendar_sync_states=selection_state["states"],
        calendar_options_json=json.dumps(calendar_options),
        selected_calendar_ids_json=json.dumps(selection_state["selected_ids"]),
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

        selection_state, my_busy = db.get_user_calendar_events_with_state(
            session.user_id, time_min, time_max
        )

        freebusy_response = await engine.freebusy_query(
            time_min, time_max, selection_state["selected_ids"]
        )
        busy_slots = []
        calendars_busy = freebusy_response.get("freebusy", {}).get("calendars", {})
        for cid in selection_state["selected_ids"]:
            busy_slots.extend(calendars_busy.get(cid, {}).get("busy", []))

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
        selection_state, _ = db.get_user_calendar_events_with_state(
            session.user_id, time_min, time_max
        )
        freebusy_response = await engine.freebusy_query(
            time_min, time_max, selection_state["selected_ids"]
        )
        busy_slots = []
        calendars_busy = freebusy_response.get("freebusy", {}).get("calendars", {})
        for cid in selection_state["selected_ids"]:
            busy_slots.extend(calendars_busy.get(cid, {}).get("busy", []))
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


@router.get("/api/calendar/event/{calendar_id}/{event_id}")
async def get_calendar_event_detail(
    calendar_id: str,
    event_id: str,
    session: Session = Depends(require_auth),
):
    event = db.get_user_calendar_event(session.user_id, calendar_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return JSONResponse({"success": True, "event": event})


@router.post("/api/calendar/event")
async def create_event(
    summary: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    add_meet: bool = Form(False),
    meeting_provider: str = Form("zoom"),
    calendar_id: Optional[str] = Form(None),
    session: Session = Depends(require_auth),
):
    try:
        attendee_list = (
            [a.strip() for a in attendees.split(",") if a.strip()]
            if attendees
            else None
        )
        target_calendar_id = (
            calendar_id or db.get_selected_calendar_ids(session.user_id)[0]
        )

        meeting_type: Optional[str] = None
        if add_meet:
            meeting_type = (
                "google_meet" if meeting_provider == "google_meet" else "addOn"
            )

        result = await engine.create_calendar_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description or None,
            location=location or None,
            attendees=attendee_list,
            add_meet=add_meet,
            meeting_type=meeting_type,
            calendar_id=target_calendar_id,
        )
        return JSONResponse(
            {"success": True, "message": "Event created", "event": result}
        )
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/calendar/api/create-event")
async def create_event_simple(
    summary: str = Form(...),
    start_date: str = Form(...),
    start_time: str = Form(...),
    end_date: str = Form(...),
    end_time: str = Form(...),
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    attendees: Optional[str] = Form(None),
    add_meet: bool = Form(False),
    meeting_provider: str = Form("zoom"),
    session: Session = Depends(require_auth),
):
    try:
        start_datetime = f"{start_date}T{start_time}:00"
        end_datetime = f"{end_date}T{end_time}:00"

        attendee_list = (
            [a.strip() for a in attendees.split(",") if a.strip()]
            if attendees
            else None
        )

        meeting_type: Optional[str] = None
        if add_meet:
            meeting_type = (
                "google_meet" if meeting_provider == "google_meet" else "addOn"
            )

        result = await engine.create_calendar_event(
            summary=summary,
            start_time=start_datetime,
            end_time=end_datetime,
            description=description or None,
            location=location or None,
            attendees=attendee_list,
            add_meet=add_meet,
            meeting_type=meeting_type,
        )
        return JSONResponse(
            {"success": True, "message": "Event created", "event": result}
        )
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/calendar/respond/{event_id}")
async def respond_to_event(
    event_id: str,
    response: str = Query(...),
    calendar_id: Optional[str] = Query(None),
    session: Session = Depends(require_auth),
):
    if response not in ("accepted", "declined", "tentative"):
        return JSONResponse(
            {"success": False, "error": "Invalid response"}, status_code=400
        )

    try:
        target_calendar_id = (
            calendar_id or db.get_selected_calendar_ids(session.user_id)[0]
        )
        result = await engine.respond_to_invite(event_id, response, target_calendar_id)
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
    link, error = _get_booking_link_context(link_id)
    context = {
        "link_id": link_id,
        "booking_link": link,
        "host_name": link.get("host_name") if link else None,
        "meeting_title": link.get("meeting_title") if link else None,
        "meeting_description": link.get("meeting_description") if link else None,
        "booking_error": error,
    }
    return templates.TemplateResponse(
        "calendar_booking.html",
        get_template_context(request, **context),
    )


@router.get("/api/calendar/booking-slots")
async def get_booking_slots(
    link_id: str = Query(...),
):
    try:
        link = _require_booking_link(link_id)
        booking_tz = _get_timezone(link.get("timezone") or "UTC")

        now = datetime.now(booking_tz)
        start_dt = now
        window_days = max(1, int(link.get("availability_days", 14)))
        end_dt = now + timedelta(days=window_days)

        calendar_id = link["calendar_id"]
        user_id = link["user_id"]
        time_min = start_dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = end_dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

        selected_ids, busy_events = db.get_user_calendar_events(
            user_id, time_min, time_max
        )
        busy_events = [
            evt for evt in busy_events if evt.get("calendarId") in {calendar_id}
        ]

        duration = max(15, int(link.get("duration_minutes", 30)))
        start_hour = max(0, min(23, int(link.get("availability_start_hour", 11))))
        end_hour = max(
            start_hour + 1, min(24, int(link.get("availability_end_hour", 22)))
        )

        slots = []
        current = start_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if current < start_dt:
            current += timedelta(days=1)

        while current < end_dt:
            if current.weekday() < 5:
                slot_end = current + timedelta(minutes=duration)
                if slot_end.hour > end_hour or slot_end.date() != current.date():
                    current = (current + timedelta(days=1)).replace(
                        hour=start_hour, minute=0
                    )
                    continue

                is_busy = False
                for event in busy_events:
                    event_start = event.get("start", {}).get("dateTime")
                    event_end = event.get("end", {}).get("dateTime")
                    if not event_start or not event_end:
                        continue
                    evt_start = datetime.fromisoformat(
                        event_start.replace("Z", "+00:00")
                    )
                    evt_end = datetime.fromisoformat(event_end.replace("Z", "+00:00"))
                    evt_start = evt_start.astimezone(booking_tz)
                    evt_end = evt_end.astimezone(booking_tz)

                    if not (slot_end <= evt_start or current >= evt_end):
                        is_busy = True
                        break

                if not is_busy and current > now:
                    slots.append(
                        {
                            "start": current.astimezone(ZoneInfo("UTC")).isoformat(),
                            "end": slot_end.astimezone(ZoneInfo("UTC")).isoformat(),
                            "display": current.strftime("%A, %B %d at %H:%M"),
                        }
                    )

            current += timedelta(minutes=duration)
            if current.hour >= end_hour:
                current = (current + timedelta(days=1)).replace(
                    hour=start_hour, minute=0
                )

        if calendar_id not in selected_ids:
            busy_events = [
                evt for evt in busy_events if evt.get("calendarId") == calendar_id
            ]

        duration = max(15, int(link.get("duration_minutes", 30)))
        start_hour = max(0, min(23, int(link.get("availability_start_hour", 11))))
        end_hour = max(
            start_hour + 1, min(24, int(link.get("availability_end_hour", 22)))
        )

        slots = []
        current = start_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if current < start_dt:
            current += timedelta(days=1)

        while current < end_dt:
            if current.weekday() < 5:
                slot_end = current + timedelta(minutes=duration)
                if slot_end.hour > end_hour or slot_end.date() != current.date():
                    current = (current + timedelta(days=1)).replace(
                        hour=start_hour, minute=0
                    )
                    continue

                is_busy = False
                for event in busy_events:
                    event_start = event.get("start", {}).get("dateTime")
                    event_end = event.get("end", {}).get("dateTime")
                    if not event_start or not event_end:
                        continue
                    evt_start = datetime.fromisoformat(
                        event_start.replace("Z", "+00:00")
                    )
                    evt_end = datetime.fromisoformat(event_end.replace("Z", "+00:00"))
                    evt_start = evt_start.astimezone(booking_tz)
                    evt_end = evt_end.astimezone(booking_tz)

                    if not (slot_end <= evt_start or current >= evt_end):
                        is_busy = True
                        break

                if not is_busy and current > now:
                    slots.append(
                        {
                            "start": current.astimezone(ZoneInfo("UTC")).isoformat(),
                            "end": slot_end.astimezone(ZoneInfo("UTC")).isoformat(),
                            "display": current.strftime("%A, %B %d at %H:%M"),
                        }
                    )

            current += timedelta(minutes=duration)
            if current.hour >= end_hour:
                current = (current + timedelta(days=1)).replace(
                    hour=start_hour, minute=0
                )

        return JSONResponse(
            {
                "success": True,
                "slots": slots[:50],
                "host_name": link.get("host_name"),
                "meeting_title": link.get("meeting_title"),
                "meeting_description": link.get("meeting_description"),
                "duration_minutes": duration,
                "timezone": link.get("timezone"),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to load booking slots for %s", link_id)
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
        link = _require_booking_link(link_id)
        summary = link.get("meeting_title") or f"Meeting with {name}"
        description = link.get("meeting_description") or "Booked via scheduling link"
        description += f"\n\nAttendee: {name} ({email})"
        if notes:
            description += f"\n\nNotes: {notes}"

        result = await engine.create_calendar_event(
            summary=summary,
            start_time=slot_start,
            end_time=slot_end,
            description=description,
            attendees=[email],
            add_meet=True,
            calendar_id=link["calendar_id"],
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Meeting booked successfully",
                "event": result,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to book meeting for %s", link_id)
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=500,
        )
