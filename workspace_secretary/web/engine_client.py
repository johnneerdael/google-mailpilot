"""
Engine API client for web UI mutations.

All database mutations go through the Engine API - the web UI never writes directly.
"""

import httpx
import os
from typing import Optional
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


def get_engine_url() -> str:
    return os.environ.get("ENGINE_API_URL", "http://localhost:8001")


ENGINE_URL = get_engine_url()


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=get_engine_url(), timeout=30)
    return _client


async def _request(method: str, path: str, json: Optional[dict] = None) -> dict:
    client = await get_client()
    try:
        response = await client.request(method, path, json=json)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        try:
            detail = e.response.json().get("detail", detail)
        except Exception:
            pass
        logger.error(f"Engine API error: {e.response.status_code} {detail}")
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except httpx.RequestError as e:
        logger.error(f"Engine API connection error: {e}")
        raise HTTPException(status_code=503, detail="Engine API unavailable")


async def mark_read(uid: int, folder: str) -> dict:
    return await _request(
        "POST", "/api/email/mark-read", {"uid": uid, "folder": folder}
    )


async def mark_unread(uid: int, folder: str) -> dict:
    return await _request(
        "POST", "/api/email/mark-unread", {"uid": uid, "folder": folder}
    )


async def move_email(uid: int, folder: str, destination: str) -> dict:
    return await _request(
        "POST",
        "/api/email/move",
        {"uid": uid, "folder": folder, "destination": destination},
    )


async def delete_email(uid: int, folder: str) -> dict:
    return await _request(
        "POST", "/api/internal/email/delete", {"uid": uid, "folder": folder}
    )


async def modify_labels(uid: int, folder: str, labels: list[str], action: str) -> dict:
    return await _request(
        "POST",
        "/api/email/labels",
        {"uid": uid, "folder": folder, "labels": labels, "action": action},
    )


async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    reply_to_message_id: Optional[str] = None,
) -> dict:
    payload = {"to": to, "subject": subject, "body": body}
    if cc:
        payload["cc"] = cc
    if bcc:
        payload["bcc"] = bcc
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    return await _request("POST", "/api/email/send", payload)


async def create_draft_reply(
    uid: int, folder: str, body: str, reply_all: bool = False
) -> dict:
    return await _request(
        "POST",
        "/api/email/draft-reply",
        {"uid": uid, "folder": folder, "body": body, "reply_all": reply_all},
    )


async def get_folders() -> dict:
    return await _request("GET", "/api/folders")


async def get_labels() -> dict:
    return await _request("GET", "/api/internal/labels")


# Calendar operations


async def get_calendar_events(
    time_min: str, time_max: str, calendar_id: str = "primary"
) -> dict:
    return await _request(
        "GET",
        f"/api/calendar/events?time_min={time_min}&time_max={time_max}&calendar_id={calendar_id}",
    )


async def get_calendar_availability(time_min: str, time_max: str) -> dict:
    return await _request(
        "GET", f"/api/calendar/availability?time_min={time_min}&time_max={time_max}"
    )


async def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[list[str]] = None,
    add_meet: bool = False,
    calendar_id: str = "primary",
) -> dict:
    payload: dict[str, str | bool | list[str]] = {
        "summary": summary,
        "start_time": start_time,
        "end_time": end_time,
        "calendar_id": calendar_id,
        "add_meet": add_meet,
    }
    if description:
        payload["description"] = description
    if location:
        payload["location"] = location
    if attendees:
        payload["attendees"] = attendees
    return await _request("POST", "/api/calendar/event", payload)


async def respond_to_invite(
    event_id: str, response: str, calendar_id: str = "primary"
) -> dict:
    return await _request(
        "POST",
        "/api/calendar/respond",
        {"event_id": event_id, "calendar_id": calendar_id, "response": response},
    )


async def get_calendar_event(calendar_id: str, event_id: str) -> dict:
    return await _request("GET", f"/api/calendar/{calendar_id}/events/{event_id}")


async def freebusy_query(
    time_min: str, time_max: str, calendar_ids: Optional[list[str]] = None
) -> dict:
    payload: dict[str, str | list[str]] = {"time_min": time_min, "time_max": time_max}
    if calendar_ids:
        payload["calendar_ids"] = calendar_ids
    return await _request("POST", "/api/calendar/freebusy", payload)
