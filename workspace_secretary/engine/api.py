import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from workspace_secretary.config import load_config, ServerConfig
from workspace_secretary.engine.imap_sync import ImapClient
from workspace_secretary.engine.calendar_sync import CalendarClient
from workspace_secretary.engine.email_cache import EmailCache
from workspace_secretary.engine.oauth2 import validate_oauth_config

logger = logging.getLogger(__name__)

SOCKET_PATH = os.environ.get("ENGINE_SOCKET", "/tmp/secretary-engine.sock")


class EngineState:
    def __init__(self):
        self.config: Optional[ServerConfig] = None
        self.imap_client: Optional[ImapClient] = None
        self.calendar_client: Optional[CalendarClient] = None
        self.email_cache: Optional[EmailCache] = None
        self.sync_task: Optional[asyncio.Task] = None
        self.running = False


state = EngineState()


class EmailMoveRequest(BaseModel):
    uid: int
    folder: str
    destination: str


class EmailMarkRequest(BaseModel):
    uid: int
    folder: str


class EmailLabelsRequest(BaseModel):
    uid: int
    folder: str
    labels: list[str]
    action: str  # "add", "remove", "set"


class CalendarEventRequest(BaseModel):
    summary: str
    start_time: str
    end_time: str
    description: Optional[str] = None
    location: Optional[str] = None
    calendar_id: str = "primary"
    meeting_type: Optional[str] = None


class MeetingResponseRequest(BaseModel):
    event_id: str
    calendar_id: str
    response: str  # "accepted", "declined", "tentative"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting secretary-engine...")

    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    state.config = load_config(config_path)

    if not state.config.imap.oauth2:
        raise RuntimeError("OAuth2 configuration required")

    validation = validate_oauth_config(state.config.imap.oauth2)
    if not validation.valid and not validation.can_refresh:
        logger.error(f"OAuth validation failed: {validation.error}")
        raise RuntimeError(validation.error)

    cache_path = os.environ.get("CACHE_DB_PATH", "config/email_cache.db")
    state.email_cache = EmailCache(cache_path)
    state.imap_client = ImapClient(
        state.config.imap,
        allowed_folders=state.config.allowed_folders,
    )

    if state.config.calendar and state.config.calendar.enabled:
        state.calendar_client = CalendarClient(state.config)

    state.imap_client.connect()
    logger.info("IMAP connected")

    if state.calendar_client:
        try:
            state.calendar_client.connect()
            logger.info("Calendar connected")
        except Exception as e:
            logger.warning(f"Calendar connection failed (non-fatal): {e}")

    state.running = True
    state.sync_task = asyncio.create_task(sync_loop())
    logger.info("Sync loop started")

    yield

    logger.info("Shutting down secretary-engine...")
    state.running = False
    if state.sync_task:
        state.sync_task.cancel()
        try:
            await state.sync_task
        except asyncio.CancelledError:
            pass

    if state.imap_client:
        state.imap_client.disconnect()

    if Path(SOCKET_PATH).exists():
        Path(SOCKET_PATH).unlink()


async def sync_loop():
    sync_interval = int(os.environ.get("SYNC_INTERVAL", "300"))

    while state.running:
        try:
            if state.email_cache and state.imap_client:
                logger.debug("Running email sync...")
                state.email_cache.sync_folder(state.imap_client, "INBOX")
        except Exception as e:
            logger.error(f"Sync error: {e}")

        await asyncio.sleep(sync_interval)


app = FastAPI(title="Secretary Engine", lifespan=lifespan)


@app.get("/api/status")
async def get_status():
    return {
        "status": "running" if state.running else "stopped",
        "imap_connected": state.imap_client is not None
        and state.imap_client.client is not None,
        "calendar_connected": state.calendar_client is not None
        and state.calendar_client.service is not None,
    }


@app.post("/api/sync/trigger")
async def trigger_sync():
    if not state.email_cache or not state.imap_client:
        raise HTTPException(status_code=503, detail="Engine not ready")

    try:
        state.email_cache.sync_folder(state.imap_client, "INBOX")
        return {"status": "ok", "message": "Sync triggered"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/move")
async def move_email(req: EmailMoveRequest):
    if not state.imap_client:
        raise HTTPException(status_code=503, detail="IMAP not connected")

    try:
        state.imap_client.move_email(req.uid, req.folder, req.destination)
        if state.email_cache:
            state.email_cache.move_email(req.uid, req.folder, req.destination)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/mark-read")
async def mark_read(req: EmailMarkRequest):
    if not state.imap_client:
        raise HTTPException(status_code=503, detail="IMAP not connected")

    try:
        state.imap_client.mark_email(req.uid, req.folder, "read")
        if state.email_cache:
            state.email_cache.mark_as_read(req.uid, req.folder)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/mark-unread")
async def mark_unread(req: EmailMarkRequest):
    if not state.imap_client:
        raise HTTPException(status_code=503, detail="IMAP not connected")

    try:
        state.imap_client.mark_email(req.uid, req.folder, "unread")
        if state.email_cache:
            state.email_cache.mark_as_unread(req.uid, req.folder)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/labels")
async def modify_labels(req: EmailLabelsRequest):
    if not state.imap_client:
        raise HTTPException(status_code=503, detail="IMAP not connected")

    try:
        if req.action == "add":
            state.imap_client.add_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "remove":
            state.imap_client.remove_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "set":
            state.imap_client.set_gmail_labels(req.uid, req.folder, req.labels)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/calendar/event")
async def create_calendar_event(req: CalendarEventRequest):
    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(status_code=503, detail="Calendar not connected")

    event_data: dict[str, Any] = {
        "summary": req.summary,
        "start": {"dateTime": req.start_time},
        "end": {"dateTime": req.end_time},
    }
    if req.description:
        event_data["description"] = req.description
    if req.location:
        event_data["location"] = req.location

    conference_version = 0
    if req.meeting_type == "google_meet":
        import uuid

        conference_version = 1
        event_data["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    try:
        event = state.calendar_client.create_event(
            event_data, req.calendar_id, conference_data_version=conference_version
        )
        return {"status": "ok", "event": event}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/calendar/respond")
async def respond_to_meeting(req: MeetingResponseRequest):
    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(status_code=503, detail="Calendar not connected")

    try:
        event = (
            state.calendar_client.service.events()
            .get(calendarId=req.calendar_id, eventId=req.event_id)
            .execute()
        )

        user_email = state.config.imap.username if state.config else None
        if not user_email:
            raise HTTPException(status_code=400, detail="User email not configured")

        attendees = event.get("attendees", [])
        for attendee in attendees:
            if attendee.get("email", "").lower() == user_email.lower():
                attendee["responseStatus"] = req.response
                break

        updated = (
            state.calendar_client.service.events()
            .patch(
                calendarId=req.calendar_id,
                eventId=req.event_id,
                body={"attendees": attendees},
            )
            .execute()
        )

        return {"status": "ok", "event": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_engine():
    if Path(SOCKET_PATH).exists():
        Path(SOCKET_PATH).unlink()

    config = uvicorn.Config(
        app,
        uds=SOCKET_PATH,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_engine()
