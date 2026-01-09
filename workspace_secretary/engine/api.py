import asyncio
import logging
import os
import smtplib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from workspace_secretary.config import load_config, ServerConfig
from workspace_secretary.engine.imap_sync import ImapClient
from workspace_secretary.engine.calendar_sync import CalendarClient, CalendarSync
from workspace_secretary.engine.database import DatabaseInterface, create_database

if TYPE_CHECKING:
    from workspace_secretary.models import Email

logger = logging.getLogger(__name__)

SOCKET_PATH = os.environ.get("ENGINE_SOCKET", "/tmp/secretary-engine.sock")

# Smart labels used by Secretary
SECRETARY_LABELS = [
    "Secretary",
    "Secretary/Priority",
    "Secretary/Action-Required",
    "Secretary/Processed",
    "Secretary/Calendar",
    "Secretary/Newsletter",
    "Secretary/Waiting",
    "Secretary/Auto-Cleaned",
    "Secretary/Drafts",
]


class EngineState:
    def __init__(self):
        self.config: Optional[ServerConfig] = None
        self.imap_client: Optional[ImapClient] = None
        self.calendar_client: Optional[CalendarClient] = None
        self.calendar_sync: Optional[CalendarSync] = None
        self.database: Optional[DatabaseInterface] = None
        self.sync_task: Optional[asyncio.Task] = None
        self.enrollment_task: Optional[asyncio.Task] = None
        self.running = False
        self.enrolled = False  # True when OAuth is valid and clients connected
        self.enrollment_error: Optional[str] = None


state = EngineState()


# Request models
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
    attendees: Optional[list[str]] = None


class MeetingResponseRequest(BaseModel):
    event_id: str
    calendar_id: str
    response: str  # "accepted", "declined", "tentative"


class SendEmailRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    cc: Optional[list[str]] = None
    bcc: Optional[list[str]] = None
    reply_to_message_id: Optional[str] = None
    in_reply_to_thread: Optional[str] = None


class DraftReplyRequest(BaseModel):
    uid: int
    folder: str
    body: str
    reply_all: bool = False


class SetupLabelsRequest(BaseModel):
    dry_run: bool = False


async def try_enroll() -> bool:
    """Attempt to connect IMAP and Calendar clients with current OAuth config.

    Returns True if enrollment successful, False otherwise.
    """
    from workspace_secretary.engine.oauth2 import validate_oauth_config

    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    token_path = Path(os.environ.get("TOKEN_PATH", "config/token.json"))

    try:
        # Load main config
        state.config = load_config(config_path)

        # If token.json exists separately, merge OAuth2 tokens from it
        if token_path.exists():
            import json
            import yaml

            try:
                with open(token_path) as f:
                    # Try JSON first (auth_setup outputs JSON)
                    content = f.read()
                    try:
                        token_data = json.loads(content)
                    except json.JSONDecodeError:
                        # Fall back to YAML
                        token_data = yaml.safe_load(content) or {}

                # Extract OAuth2 data - could be nested under 'imap.oauth2' or at root
                oauth2_data = (
                    token_data.get("imap", {}).get("oauth2")
                    or token_data.get("oauth2")
                    or token_data
                )

                if oauth2_data and "refresh_token" in oauth2_data:
                    # Merge into config using the config.py OAuth2Config
                    from workspace_secretary.config import OAuth2Config as ConfigOAuth2

                    state.config.imap.oauth2 = ConfigOAuth2(
                        client_id=oauth2_data.get(
                            "client_id",
                            state.config.imap.oauth2.client_id
                            if state.config.imap.oauth2
                            else "",
                        ),
                        client_secret=oauth2_data.get(
                            "client_secret",
                            state.config.imap.oauth2.client_secret
                            if state.config.imap.oauth2
                            else "",
                        ),
                        refresh_token=oauth2_data.get("refresh_token"),
                        access_token=oauth2_data.get("access_token"),
                        token_expiry=oauth2_data.get("token_expiry"),
                    )
                    logger.info(f"Loaded OAuth2 tokens from {token_path}")
            except Exception as e:
                logger.warning(f"Failed to load token file {token_path}: {e}")

        if not state.config.imap.oauth2:
            state.enrollment_error = "No OAuth2 configuration found"
            logger.info("Waiting for OAuth enrollment - no oauth2 config yet")
            return False

        validation = validate_oauth_config(state.config.imap.oauth2)
        if not validation.valid and not validation.can_refresh:
            state.enrollment_error = validation.error
            logger.info(f"OAuth not ready: {validation.error}")
            return False

        # Initialize database using factory (respects config.database.backend)
        state.database = create_database(state.config)
        logger.info(f"Database initialized: {type(state.database).__name__}")

        # Connect IMAP
        state.imap_client = ImapClient(
            state.config.imap,
            allowed_folders=state.config.allowed_folders,
        )
        state.imap_client.connect()
        logger.info("IMAP connected successfully")

        # Connect Calendar if enabled
        if state.config.calendar and state.config.calendar.enabled:
            state.calendar_client = CalendarClient(state.config)
            try:
                state.calendar_client.connect()
                # Initialize CalendarSync with database as cache
                # DatabaseInterface has all methods CalendarCache needs
                state.calendar_sync = CalendarSync(
                    state.calendar_client,
                    state.database,  # type: ignore[arg-type]
                )
                logger.info("Calendar connected successfully")
            except Exception as e:
                logger.warning(f"Calendar connection failed (non-fatal): {e}")

        state.enrolled = True
        state.enrollment_error = None
        return True

    except Exception as e:
        state.enrollment_error = str(e)
        logger.warning(f"Enrollment attempt failed: {e}")
        # Clean up partial state
        if state.imap_client:
            try:
                state.imap_client.disconnect()
            except Exception:
                pass
            state.imap_client = None
        state.calendar_client = None
        state.calendar_sync = None
        state.database = None
        return False


async def enrollment_watch_loop():
    """Watch for OAuth enrollment and auto-connect when ready.

    Monitors config/token files for changes and attempts enrollment.
    """
    token_path = Path(os.environ.get("TOKEN_PATH", "config/token.json"))
    config_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))

    last_token_mtime = 0.0
    last_config_mtime = 0.0
    check_interval = 5  # Check every 5 seconds

    logger.info("Starting enrollment watch loop...")

    while state.running and not state.enrolled:
        try:
            # Check if token or config files have changed
            token_changed = False
            config_changed = False

            if token_path.exists():
                current_mtime = token_path.stat().st_mtime
                if current_mtime > last_token_mtime:
                    token_changed = True
                    last_token_mtime = current_mtime
                    logger.info("Detected token.json change")

            if config_path.exists():
                current_mtime = config_path.stat().st_mtime
                if current_mtime > last_config_mtime:
                    config_changed = True
                    last_config_mtime = current_mtime
                    logger.info("Detected config.yaml change")

            # Attempt enrollment if files changed or on first run
            if (
                token_changed
                or config_changed
                or (last_token_mtime == 0 and last_config_mtime == 0)
            ):
                if last_token_mtime == 0 and last_config_mtime == 0:
                    # First run - record current mtimes
                    if token_path.exists():
                        last_token_mtime = token_path.stat().st_mtime
                    if config_path.exists():
                        last_config_mtime = config_path.stat().st_mtime

                if await try_enroll():
                    logger.info("Enrollment successful! Starting sync loop.")
                    state.sync_task = asyncio.create_task(sync_loop())
                    return

        except Exception as e:
            logger.error(f"Error in enrollment watch loop: {e}")

        await asyncio.sleep(check_interval)

    logger.info("Enrollment watch loop ended")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler - starts engine in waiting mode if OAuth not ready."""
    logger.info("Starting secretary-engine...")

    state.running = True

    # Try immediate enrollment
    if await try_enroll():
        logger.info("OAuth ready - starting sync loop immediately")
        state.sync_task = asyncio.create_task(sync_loop())
    else:
        # No OAuth yet - start watching for enrollment
        logger.info("OAuth not configured - waiting for enrollment...")
        logger.info("Run 'auth_setup' to complete OAuth enrollment")
        state.enrollment_task = asyncio.create_task(enrollment_watch_loop())

    yield

    logger.info("Shutting down secretary-engine...")
    state.running = False

    if state.sync_task:
        state.sync_task.cancel()
        try:
            await state.sync_task
        except asyncio.CancelledError:
            pass

    if state.enrollment_task:
        state.enrollment_task.cancel()
        try:
            await state.enrollment_task
        except asyncio.CancelledError:
            pass

    if state.imap_client:
        state.imap_client.disconnect()

    if Path(SOCKET_PATH).exists():
        Path(SOCKET_PATH).unlink()


async def sync_loop():
    """Background sync loop for email and calendar."""
    sync_interval = int(os.environ.get("SYNC_INTERVAL", "300"))

    while state.running:
        try:
            # Email sync
            if state.database and state.imap_client:
                logger.debug("Running email sync...")
                await sync_emails()

            # Calendar sync
            if state.calendar_sync:
                logger.debug("Running calendar sync...")
                await sync_calendar()

            # Generate embeddings if supported (PostgreSQL with pgvector)
            if state.database and state.database.supports_embeddings():
                logger.debug("Generating embeddings for new emails...")
                await generate_embeddings()

        except Exception as e:
            logger.error(f"Sync error: {e}")

        await asyncio.sleep(sync_interval)


def _email_to_db_params(email_obj: "Email", folder: str) -> dict[str, Any]:
    """Convert Email dataclass to database upsert parameters."""
    return {
        "uid": email_obj.uid or 0,
        "folder": folder,
        "message_id": email_obj.message_id,
        "subject": email_obj.subject,
        "from_addr": str(email_obj.from_),
        "to_addr": [str(addr) for addr in email_obj.to],
        "cc_addr": [str(addr) for addr in email_obj.cc],
        "date": email_obj.date,
        "body_text": email_obj.content.text,
        "body_html": email_obj.content.html,
        "flags": email_obj.flags,
        "is_unread": "\\Seen" not in email_obj.flags,
        "is_important": "\\Flagged" in email_obj.flags,
        "size": 0,  # Not available from IMAP fetch
        "in_reply_to": email_obj.in_reply_to,
        "references_header": " ".join(email_obj.references)
        if email_obj.references
        else None,
    }


async def sync_emails():
    """Sync emails from IMAP to database."""
    if not state.database or not state.imap_client:
        return

    # Get allowed folders from config, default to INBOX
    folders = ["INBOX"]
    if state.config and state.config.allowed_folders:
        folders = state.config.allowed_folders

    for folder in folders:
        try:
            # Get folder state for incremental sync
            folder_state = state.database.get_folder_state(folder)
            last_uid = folder_state.get("uidnext", 1) if folder_state else 1

            # Search for emails with UID > last_uid
            # Use uid_range criteria to get new emails
            uids = state.imap_client.search(
                {"uid_range": (last_uid, "*")},
                folder=folder,
            )

            if not uids:
                continue

            # Fetch the emails
            emails = state.imap_client.fetch_emails(uids, folder, limit=500)

            max_uid = last_uid
            for uid, email_obj in emails.items():
                # Convert Email dataclass to db params and upsert
                params = _email_to_db_params(email_obj, folder)
                state.database.upsert_email(**params)
                if uid > max_uid:
                    max_uid = uid

            # Update folder state with new uidnext
            if max_uid >= last_uid:
                # Get folder info for uidvalidity
                folder_info = state.imap_client.select_folder(folder, readonly=True)
                uidvalidity = folder_info.get(b"UIDVALIDITY", 0)
                state.database.save_folder_state(
                    folder=folder,
                    uidvalidity=uidvalidity,
                    uidnext=max_uid + 1,
                )

            logger.debug(f"Synced {len(emails)} emails from {folder}")

        except Exception as e:
            logger.error(f"Error syncing folder {folder}: {e}")


async def sync_calendar():
    """Sync calendar events to database."""
    if not state.calendar_sync:
        return

    try:
        # Sync primary calendar
        state.calendar_sync.sync_calendar("primary")

        # Sync additional calendars if configured
        if state.config and state.config.calendar:
            for cal_id in getattr(state.config.calendar, "additional_calendars", []):
                state.calendar_sync.sync_calendar(cal_id)

    except Exception as e:
        logger.error(f"Calendar sync error: {e}")


async def generate_embeddings():
    """Generate embeddings for emails that don't have them yet."""
    if not state.database or not state.database.supports_embeddings():
        return

    # Check if embeddings are configured
    if not state.config or not state.config.database.embeddings:
        return

    embeddings_config = state.config.database.embeddings
    if not embeddings_config.enabled:
        return

    # Get folders to process
    folders = ["INBOX"]
    if state.config.allowed_folders:
        folders = state.config.allowed_folders

    try:
        # Import and create embeddings client (lazy import)
        try:
            from workspace_secretary.engine.embeddings import (
                EmbeddingsSyncWorker,
                create_embeddings_client,
            )
        except ImportError:
            logger.debug(
                "Embeddings module not available, skipping embedding generation"
            )
            return

        client = create_embeddings_client(embeddings_config)
        if not client:
            return

        worker = EmbeddingsSyncWorker(
            client=client,
            database=state.database,
            folders=folders,
            batch_size=50,
        )

        total = await worker.sync_all_folders()
        if total > 0:
            logger.debug(f"Generated embeddings for {total} emails")

    except Exception as e:
        logger.error(f"Embedding generation error: {e}")


app = FastAPI(title="Secretary Engine", lifespan=lifespan)


# ============================================================================
# Status endpoints
# ============================================================================


@app.get("/api/status")
async def get_status():
    return {
        "status": "running" if state.running else "stopped",
        "enrolled": state.enrolled,
        "enrollment_error": state.enrollment_error,
        "imap_connected": state.imap_client is not None
        and state.imap_client.client is not None,
        "calendar_connected": state.calendar_client is not None
        and state.calendar_client.service is not None,
        "database_type": type(state.database).__name__ if state.database else None,
        "embeddings_enabled": state.database.supports_embeddings()
        if state.database
        else False,
        "waiting_for_oauth": state.running and not state.enrolled,
    }


# ============================================================================
# Sync endpoints
# ============================================================================


@app.post("/api/sync/trigger")
async def trigger_sync():
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.database or not state.imap_client:
        return {"status": "error", "message": "Engine not ready"}

    try:
        await sync_emails()
        if state.calendar_sync:
            await sync_calendar()
        return {"status": "ok", "message": "Sync triggered"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# Email mutation endpoints
# ============================================================================


@app.post("/api/email/move")
async def move_email(req: EmailMoveRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.imap_client:
        return {"status": "error", "message": "IMAP not connected"}

    try:
        state.imap_client.move_email(req.uid, req.folder, req.destination)
        # Update database
        if state.database:
            # Delete from old location, will be re-synced in new location
            state.database.delete_email(req.uid, req.folder)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/email/mark-read")
async def mark_read(req: EmailMarkRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.imap_client:
        return {"status": "error", "message": "IMAP not connected"}

    try:
        state.imap_client.mark_email(req.uid, req.folder, "read")
        if state.database:
            state.database.mark_email_read(req.uid, req.folder, True)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/email/mark-unread")
async def mark_unread(req: EmailMarkRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.imap_client:
        return {"status": "error", "message": "IMAP not connected"}

    try:
        state.imap_client.mark_email(req.uid, req.folder, "unread")
        if state.database:
            state.database.mark_email_read(req.uid, req.folder, False)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/email/labels")
async def modify_labels(req: EmailLabelsRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.imap_client:
        return {"status": "error", "message": "IMAP not connected"}

    try:
        if req.action == "add":
            state.imap_client.add_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "remove":
            state.imap_client.remove_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "set":
            state.imap_client.set_gmail_labels(req.uid, req.folder, req.labels)
        else:
            return {"status": "error", "message": f"Invalid action: {req.action}"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/email/send")
async def send_email(req: SendEmailRequest):
    """Send an email via SMTP/Gmail API."""
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.config:
        return {"status": "error", "message": "Configuration not loaded"}

    try:
        # Build the email message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = req.subject
        msg["From"] = state.config.imap.username
        msg["To"] = ", ".join(req.to)

        if req.cc:
            msg["Cc"] = ", ".join(req.cc)

        if req.reply_to_message_id:
            msg["In-Reply-To"] = req.reply_to_message_id
            msg["References"] = req.reply_to_message_id

        # Add body as plain text
        msg.attach(MIMEText(req.body, "plain"))

        # Send via Gmail SMTP with OAuth2
        if state.config.imap.oauth2 and state.config.imap.oauth2.access_token:
            import base64

            # Use Gmail API for sending (more reliable with OAuth)
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                token=state.config.imap.oauth2.access_token,
                refresh_token=state.config.imap.oauth2.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=state.config.imap.oauth2.client_id,
                client_secret=state.config.imap.oauth2.client_secret,
            )

            service = build("gmail", "v1", credentials=creds)

            # Encode the message
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

            # Send
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw_message})
                .execute()
            )

            return {"status": "ok", "message_id": result.get("id")}

        else:
            # Fallback to SMTP (requires password)
            return {
                "status": "error",
                "message": "OAuth2 required for sending emails",
            }

    except Exception as e:
        logger.error(f"Send email error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/email/draft-reply")
async def create_draft_reply(req: DraftReplyRequest):
    """Create a draft reply to an email."""
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.database or not state.config:
        return {"status": "error", "message": "Engine not ready"}

    try:
        # Get the original email
        original = state.database.get_email_by_uid(req.uid, req.folder)
        if not original:
            return {"status": "error", "message": "Original email not found"}

        # Build reply recipients
        reply_to = original.get("reply_to") or original.get("from_addr", "")
        recipients = [reply_to] if reply_to else []

        if req.reply_all:
            # Add all original recipients except self
            user_email = state.config.imap.username.lower()
            to_addrs = original.get("to_addr", [])
            if isinstance(to_addrs, str):
                to_addrs = [to_addrs]
            cc_addrs = original.get("cc_addr", [])
            if isinstance(cc_addrs, str):
                cc_addrs = [cc_addrs]
            for addr in to_addrs:
                if addr.lower() != user_email and addr not in recipients:
                    recipients.append(addr)
            for addr in cc_addrs:
                if addr.lower() != user_email and addr not in recipients:
                    recipients.append(addr)

        # Build subject
        subject = original.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build the draft message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = state.config.imap.username
        msg["To"] = ", ".join(recipients)
        msg["In-Reply-To"] = original.get("message_id", "")
        msg["References"] = original.get("message_id", "")

        msg.attach(MIMEText(req.body, "plain"))

        # Create draft via Gmail API
        if state.config.imap.oauth2 and state.config.imap.oauth2.access_token:
            import base64

            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                token=state.config.imap.oauth2.access_token,
                refresh_token=state.config.imap.oauth2.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=state.config.imap.oauth2.client_id,
                client_secret=state.config.imap.oauth2.client_secret,
            )

            service = build("gmail", "v1", credentials=creds)

            # Encode the message
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

            # Create draft
            draft = (
                service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw_message}})
                .execute()
            )

            return {
                "status": "ok",
                "draft_id": draft.get("id"),
                "recipients": recipients,
                "subject": subject,
            }

        else:
            return {
                "status": "error",
                "message": "OAuth2 required for creating drafts",
            }

    except Exception as e:
        logger.error(f"Create draft error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/email/setup-labels")
async def setup_labels(req: SetupLabelsRequest):
    """Create Secretary label hierarchy in Gmail."""
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.config or not state.config.imap.oauth2:
        return {"status": "error", "message": "OAuth2 configuration required"}

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=state.config.imap.oauth2.access_token,
            refresh_token=state.config.imap.oauth2.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=state.config.imap.oauth2.client_id,
            client_secret=state.config.imap.oauth2.client_secret,
        )

        service = build("gmail", "v1", credentials=creds)

        # Get existing labels
        results = service.users().labels().list(userId="me").execute()
        existing_labels = {label["name"]: label for label in results.get("labels", [])}

        created = []
        already_exists = []

        for label_name in SECRETARY_LABELS:
            if label_name in existing_labels:
                already_exists.append(label_name)
                continue

            if req.dry_run:
                created.append(f"{label_name} (would create)")
            else:
                # Create the label
                label_body = {
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                }
                service.users().labels().create(userId="me", body=label_body).execute()
                created.append(label_name)

        return {
            "status": "ok",
            "dry_run": req.dry_run,
            "created": created,
            "already_exists": already_exists,
        }

    except Exception as e:
        logger.error(f"Setup labels error: {e}")
        return {"status": "error", "message": str(e)}


# ============================================================================
# Calendar endpoints
# ============================================================================


@app.get("/api/calendar/events")
async def list_calendar_events(
    time_min: Optional[str] = Query(None, description="Start time (ISO format)"),
    time_max: Optional[str] = Query(None, description="End time (ISO format)"),
    calendar_id: str = Query("primary", description="Calendar ID"),
):
    """List calendar events within a time range."""
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.calendar_client or not state.calendar_client.service:
        return {"status": "error", "message": "Calendar not connected"}

    try:
        # Default to next 7 days if not specified
        if not time_min:
            time_min = datetime.utcnow().isoformat() + "Z"
        if not time_max:
            time_max = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

        events = state.calendar_client.list_events(time_min, time_max, calendar_id)
        return {"status": "ok", "events": events}

    except Exception as e:
        logger.error(f"List calendar events error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/calendar/availability")
async def get_calendar_availability(
    time_min: str = Query(..., description="Start time (ISO format)"),
    time_max: str = Query(..., description="End time (ISO format)"),
):
    """Get free/busy information for the user's calendars."""
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.calendar_client or not state.calendar_client.service:
        return {"status": "error", "message": "Calendar not connected"}

    try:
        availability = state.calendar_client.get_availability(time_min, time_max)
        return {"status": "ok", "availability": availability}

    except Exception as e:
        logger.error(f"Get availability error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/calendar/event")
async def create_calendar_event(req: CalendarEventRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.calendar_client or not state.calendar_client.service:
        return {"status": "error", "message": "Calendar not connected"}

    event_data: dict[str, Any] = {
        "summary": req.summary,
        "start": {"dateTime": req.start_time},
        "end": {"dateTime": req.end_time},
    }
    if req.description:
        event_data["description"] = req.description
    if req.location:
        event_data["location"] = req.location
    if req.attendees:
        event_data["attendees"] = [{"email": email} for email in req.attendees]

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

        # Also save to database
        if state.database and event:
            state.database.upsert_event(
                event={
                    "event_id": event.get("id"),
                    "summary": req.summary,
                    "start_time": req.start_time,
                    "end_time": req.end_time,
                    "description": req.description,
                    "location": req.location,
                    "status": "confirmed",
                    "raw_json": event,
                },
                calendar_id=req.calendar_id,
            )

        return {"status": "ok", "event": event}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/calendar/respond")
async def respond_to_meeting(req: MeetingResponseRequest):
    if not state.enrolled:
        return {
            "status": "no_account",
            "message": "No account configured. Run auth_setup to add an account.",
        }

    if not state.calendar_client or not state.calendar_client.service:
        return {"status": "error", "message": "Calendar not connected"}

    try:
        event = (
            state.calendar_client.service.events()
            .get(calendarId=req.calendar_id, eventId=req.event_id)
            .execute()
        )

        user_email = state.config.imap.username if state.config else None
        if not user_email:
            return {"status": "error", "message": "User email not configured"}

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
        return {"status": "error", "message": str(e)}


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
