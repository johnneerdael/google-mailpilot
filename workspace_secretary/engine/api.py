import asyncio
import logging
import os
import smtplib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import re
from email.message import EmailMessage
from email.utils import parseaddr, make_msgid

import idna
import imapclient
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Optional, TYPE_CHECKING, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import io

from workspace_secretary.config import load_config, ServerConfig, ImapConfig
from workspace_secretary.engine.imap_sync import ImapClient
from workspace_secretary.engine.calendar_sync import CalendarClient
from workspace_secretary.db import DatabaseInterface
from workspace_secretary.engine.database import create_database
from workspace_secretary.engine.analysis import PhishingAnalyzer
from workspace_secretary.smtp_client import SMTPClient

if TYPE_CHECKING:
    from workspace_secretary.models import Email

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)

MAX_SYNC_CONNECTIONS = int(os.environ.get("MAX_SYNC_CONNECTIONS", "5"))

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
        self.idle_client: Optional[ImapClient] = None
        self.calendar_client: Optional[CalendarClient] = None
        self.database: Optional[DatabaseInterface] = None
        self.phishing_analyzer = PhishingAnalyzer()
        self.sync_task: Optional[asyncio.Task] = None
        self.idle_task: Optional[asyncio.Task] = None
        self.idle_enabled: bool = False
        self.embeddings_task: Optional[asyncio.Task] = None
        self.enrollment_task: Optional[asyncio.Task] = None
        self.running = False
        self.enrolled = False
        self.enrollment_error: Optional[str] = None
        self._sync_debounce_task: Optional[asyncio.Task] = None
        self._sync_debounce_delay: float = 2.0
        self._embeddings_consecutive_failures: int = 0
        self._embeddings_cooldown_until: Optional[datetime] = None
        self._sync_executor: Optional[ThreadPoolExecutor] = None
        self._imap_pool: Queue[ImapClient] = Queue()
        self._imap_pool_size: int = 0
        self._pool_init_lock: Optional[asyncio.Lock] = (
            None  # Initialized lazily per event loop
        )


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


class FreeBusyRequest(BaseModel):
    time_min: str
    time_max: str
    calendar_ids: Optional[list[str]] = None


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
    from workspace_secretary.config import merge_oauth2_tokens
    from workspace_secretary.engine.oauth2 import validate_oauth_config

    config_path = os.environ.get("CONFIG_PATH")

    try:
        state.config = load_config(config_path)
        merge_oauth2_tokens(state.config)

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
        state.database = create_database(state.config.database)
        state.database.initialize()
        logger.info(f"Database initialized: {type(state.database).__name__}")

        # Connect IMAP
        state.imap_client = ImapClient(
            state.config.imap,
            allowed_folders=state.config.allowed_folders,
        )
        state.imap_client.connect()
        logger.info("IMAP connected successfully")

        # Create separate IDLE client for push notifications
        if state.imap_client.has_idle_capability():
            state.idle_client = ImapClient(
                state.config.imap,
                allowed_folders=["INBOX"],
            )
            state.idle_client.connect()
            logger.info("IDLE client connected for push notifications")

        # Connect Calendar if enabled
        if state.config.calendar and state.config.calendar.enabled:
            state.calendar_client = CalendarClient(state.config)
            try:
                state.calendar_client.connect()
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
        if state.idle_client:
            try:
                state.idle_client.disconnect()
            except Exception:
                pass
            state.idle_client = None
        state.calendar_client = None
        state.database = None
        return False


async def enrollment_watch_loop():
    """Watch for OAuth enrollment and auto-connect when ready.

    Monitors config/token files for changes and attempts enrollment.
    """
    token_path = Path(os.environ.get("TOKEN_PATH", "config/token.json"))
    config_path_env = os.environ.get("CONFIG_PATH")

    # Find actual config path using same search logic as load_config
    config_path: Optional[Path] = None
    if config_path_env:
        config_path = Path(config_path_env)
    else:
        search_paths = [
            Path("/app/config/config.yaml"),
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path.home() / ".config/workspace-secretary/config.yaml",
            Path("/etc/workspace-secretary/config.yaml"),
        ]
        for p in search_paths:
            if p.exists():
                config_path = p
                break

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

            if config_path and config_path.exists():
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
                    if config_path and config_path.exists():
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

    _shutdown_connection_pool()

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

    if state.idle_client:
        state.idle_client.disconnect()

    if Path(SOCKET_PATH).exists():
        Path(SOCKET_PATH).unlink()


async def embeddings_loop():
    """Best-effort background embeddings generation. Never blocks IMAP sync."""
    max_consecutive_failures = 5
    cooldown_minutes = 10
    idle_sleep = 30

    logger.info("Embeddings loop started")

    while state.running:
        try:
            if state._embeddings_cooldown_until:
                if datetime.now() < state._embeddings_cooldown_until:
                    remaining = (
                        state._embeddings_cooldown_until - datetime.now()
                    ).seconds
                    logger.debug(f"Embeddings in cooldown, {remaining}s remaining")
                    await asyncio.sleep(idle_sleep)
                    continue
                else:
                    state._embeddings_cooldown_until = None
                    state._embeddings_consecutive_failures = 0
                    logger.info("Embeddings cooldown ended, resuming")

            embedded = await generate_embeddings()
            state._embeddings_consecutive_failures = 0

            if not embedded:
                await asyncio.sleep(idle_sleep)

        except Exception as e:
            state._embeddings_consecutive_failures += 1
            logger.error(
                f"Embeddings error ({state._embeddings_consecutive_failures}/{max_consecutive_failures}): {e}"
            )

            if state._embeddings_consecutive_failures >= max_consecutive_failures:
                state._embeddings_cooldown_until = datetime.now() + timedelta(
                    minutes=cooldown_minutes
                )
                logger.warning(
                    f"Embeddings paused for {cooldown_minutes} minutes after {max_consecutive_failures} failures"
                )
            await asyncio.sleep(idle_sleep)


async def sync_loop():
    """Background sync loop for email and calendar.

    - Initial sync: lockstep batch sync+embed (50 emails at a time)
    - After initial: IDLE handles INBOX push, periodic sync catches missed updates
    - Embeddings loop starts after initial sync for steady-state
    """
    catchup_interval = int(
        os.environ.get("SYNC_CATCHUP_INTERVAL", "1800")
    )  # 30 min default
    logger.info("Sync loop started")

    initial_sync_done = False

    while state.running:
        try:
            if state.database and state.config:
                if not initial_sync_done:
                    logger.info("Running initial lockstep sync+embed...")
                    await initial_lockstep_sync_and_embed()
                    initial_sync_done = True

                    if state.database.supports_embeddings():
                        logger.info(
                            "Starting embeddings background task for steady-state"
                        )
                        state.embeddings_task = asyncio.create_task(embeddings_loop())

                    if (
                        not state.idle_enabled
                        and state.idle_client
                        and state.idle_client.has_idle_capability()
                    ):
                        logger.info("Starting IDLE monitor for push notifications")
                        state.idle_task = asyncio.create_task(idle_monitor())
                        state.idle_enabled = True

                    logger.info(
                        f"Initial sync complete. Catch-up every {catchup_interval}s"
                    )
                else:
                    logger.debug("Running periodic catch-up sync...")
                    await sync_emails_parallel()
        except Exception as e:
            logger.error(f"Sync error: {e}")

        if initial_sync_done:
            await asyncio.sleep(catchup_interval)
        else:
            await asyncio.sleep(5)


def _init_connection_pool():
    """Initialize the IMAP connection pool for parallel sync."""
    if not state.config:
        return

    pool_size = min(
        MAX_SYNC_CONNECTIONS, len(state.config.allowed_folders or ["INBOX"])
    )
    state._sync_executor = ThreadPoolExecutor(
        max_workers=pool_size, thread_name_prefix="imap-sync"
    )

    logger.info(f"Creating {pool_size} IMAP connections for sync pool...")

    for i in range(pool_size):
        try:
            logger.debug(f"Connecting sync connection {i + 1}/{pool_size}...")
            client = ImapClient(
                state.config.imap,
                allowed_folders=state.config.allowed_folders,
            )
            client.connect()
            state._imap_pool.put(client)
            state._imap_pool_size += 1
            logger.debug(f"Created sync connection {i + 1}/{pool_size}")
        except Exception as e:
            logger.error(f"Failed to create sync connection {i + 1}: {e}")

    logger.info(
        f"IMAP connection pool initialized with {state._imap_pool_size} connections"
    )


def _shutdown_connection_pool():
    """Shutdown the IMAP connection pool."""
    if state._sync_executor:
        state._sync_executor.shutdown(wait=False)
        state._sync_executor = None

    while not state._imap_pool.empty():
        try:
            client = state._imap_pool.get_nowait()
            try:
                client.disconnect()
            except Exception:
                pass
        except Empty:
            break

    state._imap_pool_size = 0
    logger.info("IMAP connection pool shutdown")


def _sync_folder_worker(folder: str) -> int:
    """Sync a single folder using a connection from the pool.

    Returns the number of emails synced.
    """
    if not state.database or not state.config:
        return 0

    try:
        client = state._imap_pool.get(timeout=60)
    except Empty:
        logger.warning(f"No available connection for folder {folder}")
        return 0

    try:
        return _sync_single_folder(client, folder)
    finally:
        state._imap_pool.put(client)


def _sync_single_folder(client: ImapClient, folder: str) -> int:
    """Sync a single folder with the given client. Returns emails synced."""
    if not state.database:
        return 0

    try:
        folder_state = state.database.get_folder_state(folder)
        folder_info = client.select_folder(folder, readonly=True)

        current_uidvalidity = folder_info.get("uidvalidity", 0)
        current_highestmodseq = folder_info.get("highestmodseq", 0)

        stored_uidvalidity = folder_state.get("uidvalidity", 0) if folder_state else 0
        stored_highestmodseq = (
            folder_state.get("highestmodseq", 0) if folder_state else 0
        )
        stored_uidnext = folder_state.get("uidnext", 1) if folder_state else 1

        if stored_uidvalidity != current_uidvalidity and stored_uidvalidity != 0:
            logger.warning(f"UIDVALIDITY changed for {folder}, clearing cache")
            state.database.clear_folder(folder)
            stored_uidnext = 1
            stored_highestmodseq = 0

        has_condstore = client.has_condstore_capability()

        if (
            has_condstore
            and stored_highestmodseq > 0
            and current_highestmodseq == stored_highestmodseq
        ):
            logger.debug(f"HIGHESTMODSEQ unchanged for {folder}, skipping sync")
            return 0

        if has_condstore and stored_highestmodseq > 0:
            changed = client.fetch_changed_since(folder, stored_highestmodseq)
            for uid, data in changed.items():
                state.database.update_email_flags(
                    uid=uid,
                    folder=folder,
                    flags=",".join(data["flags"]),
                    is_unread="\\Seen" not in data["flags"],
                    modseq=data["modseq"],
                    gmail_labels=data.get("gmail_labels"),
                )
            if changed:
                logger.info(f"Updated flags for {len(changed)} emails in {folder}")

        uids = client.search(f"UID {stored_uidnext}:*", folder=folder)
        new_uids = [uid for uid in uids if uid >= stored_uidnext]

        total_synced = 0
        total_to_sync = len(new_uids) if new_uids else 0

        if new_uids:
            new_uids_desc = sorted(new_uids, reverse=True)
            logger.info(f"[{folder}] Starting sync of {total_to_sync} emails")

            for i in range(0, len(new_uids_desc), 50):
                batch = new_uids_desc[i : i + 50]
                emails = client.fetch_emails(batch, folder, limit=50)
                for uid, email_obj in emails.items():
                    params = _email_to_db_params(email_obj, folder)
                    state.database.upsert_email(**params)
                total_synced += len(emails)
                logger.info(f"[{folder}] {total_synced}/{total_to_sync} emails synced")

            max_uid = max(new_uids)
        else:
            max_uid = stored_uidnext - 1

        state.database.save_folder_state(
            folder=folder,
            uidvalidity=current_uidvalidity,
            uidnext=max_uid + 1,
            highestmodseq=current_highestmodseq,
        )

        return total_synced

    except Exception as e:
        logger.error(f"Error syncing folder {folder}: {e}")
        return 0


def _sync_next_batch(
    client: ImapClient,
    folder: str,
    batch_size: int = 50,
    synced_uids_set: set[int] | None = None,
) -> tuple[list[int], bool]:
    """Sync next batch of emails not yet in DB.

    Returns (synced_uids, has_more).
    """
    if not state.database or not state.config:
        return [], False

    try:
        folder_info = client.select_folder(folder, readonly=True)
        current_uidvalidity = folder_info.get("uidvalidity", 0)
        current_highestmodseq = folder_info.get("highestmodseq", 0)

        all_imap_uids = client.search("ALL", folder=folder)

        if synced_uids_set is None:
            synced_uids_set = set(state.database.get_synced_uids(folder))

        missing_uids = sorted(
            [uid for uid in all_imap_uids if uid not in synced_uids_set]
        )

        if not missing_uids:
            state.database.save_folder_state(
                folder=folder,
                uidvalidity=current_uidvalidity,
                uidnext=max(all_imap_uids) + 1 if all_imap_uids else 1,
                highestmodseq=current_highestmodseq,
            )
            return [], False

        batch_uids = missing_uids[:batch_size]
        emails = client.fetch_emails(batch_uids, folder, limit=batch_size)

        synced_uids: list[int] = []
        for uid, email_obj in emails.items():
            params = _email_to_db_params(email_obj, folder)
            state.database.upsert_email(**params)
            synced_uids.append(uid)

        has_more = len(missing_uids) > batch_size

        if not has_more:
            state.database.save_folder_state(
                folder=folder,
                uidvalidity=current_uidvalidity,
                uidnext=max(all_imap_uids) + 1 if all_imap_uids else 1,
                highestmodseq=current_highestmodseq,
            )

        return synced_uids, has_more

    except Exception as e:
        logger.error(f"Error in batch sync for {folder}: {e}")
        return [], False


async def sync_emails_parallel():
    """Sync all folders in parallel using the connection pool."""
    if not state.database or not state.config:
        return

    if state._pool_init_lock is None:
        state._pool_init_lock = asyncio.Lock()

    if state._imap_pool_size == 0:
        async with state._pool_init_lock:
            if state._imap_pool_size == 0:
                logger.info("Initializing IMAP connection pool...")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _init_connection_pool)

    if state._imap_pool_size == 0:
        logger.error("No IMAP connections available after pool init")
        return

    folders = state.config.allowed_folders or ["INBOX"]
    loop = asyncio.get_running_loop()

    tasks = [
        loop.run_in_executor(state._sync_executor, _sync_folder_worker, folder)
        for folder in folders
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    total = sum(r for r in results if isinstance(r, int))
    errors = [r for r in results if isinstance(r, Exception)]

    if errors:
        for e in errors:
            logger.error(f"Folder sync error: {e}")

    if total > 0:
        logger.info(
            f"Parallel sync complete: {total} emails across {len(folders)} folders"
        )


def _email_to_db_params(email_obj: "Email", folder: str) -> dict[str, Any]:
    """Convert Email dataclass to database upsert parameters."""
    date_str = email_obj.date.isoformat() if email_obj.date else None
    internal_date_str = (
        email_obj.internal_date.isoformat() if email_obj.internal_date else None
    )
    gmail_thread_id = (
        int(email_obj.gmail_thread_id) if email_obj.gmail_thread_id else None
    )

    headers = email_obj.headers or {}
    if not isinstance(headers, dict):
        headers = {}

    analysis = state.phishing_analyzer.analyze_email(
        {
            "from_addr": str(email_obj.from_),
            "headers": headers,
            "reply_to": headers.get("Reply-To"),
        }
    )

    auth = analysis["auth_results"]
    signals = analysis["signals"]

    is_suspicious_sender = (
        signals["reply_to_differs"]
        or signals["display_name_mismatch"]
        or signals["punycode_domain"]
    )

    return {
        "uid": email_obj.uid or 0,
        "folder": folder,
        "message_id": email_obj.message_id,
        "subject": email_obj.subject,
        "from_addr": str(email_obj.from_),
        "to_addr": ",".join(str(addr) for addr in email_obj.to),
        "cc_addr": ",".join(str(addr) for addr in email_obj.cc),
        "bcc_addr": "",
        "date": date_str,
        "internal_date": internal_date_str,
        "body_text": email_obj.content.text or "",
        "body_html": email_obj.content.html or "",
        "flags": ",".join(email_obj.flags),
        "is_unread": "\\Seen" not in email_obj.flags,
        "is_important": "\\Flagged" in email_obj.flags,
        "size": email_obj.size,
        "modseq": email_obj.modseq,
        "in_reply_to": email_obj.in_reply_to or "",
        "references_header": " ".join(email_obj.references)
        if email_obj.references
        else "",
        "gmail_thread_id": gmail_thread_id,
        "gmail_msgid": email_obj.gmail_msgid,
        "gmail_labels": email_obj.gmail_labels,
        "has_attachments": email_obj.has_attachments,
        "attachment_filenames": email_obj.attachment_filenames,
        "auth_results_raw": auth["auth_results_raw"],
        "spf": auth["spf"],
        "dkim": auth["dkim"],
        "dmarc": auth["dmarc"],
        "is_suspicious_sender": is_suspicious_sender,
        "security_score": analysis["score"],
        "warning_type": analysis["warning_type"],
        "suspicious_sender_signals": {
            "reply_to_differs": signals["reply_to_differs"],
            "display_name_mismatch": signals["display_name_mismatch"],
            "punycode_domain": signals["punycode_domain"],
        },
    }


async def generate_embeddings() -> int:
    """Generate embeddings for emails that don't have them yet."""
    if not state.database or not state.database.supports_embeddings():
        logger.debug("Embeddings: database doesn't support embeddings")
        return 0

    if not state.config or not state.config.database.embeddings:
        logger.debug("Embeddings: not configured in config.yaml")
        return 0

    embeddings_config = state.config.database.embeddings
    if not embeddings_config.enabled:
        logger.debug("Embeddings: disabled in config")
        return 0

    folders = ["INBOX"]
    if state.config.allowed_folders:
        folders = state.config.allowed_folders

    try:
        try:
            from workspace_secretary.engine.embeddings import (
                EmbeddingsSyncWorker,
                create_embeddings_client,
            )
        except ImportError:
            logger.debug(
                "Embeddings module not available, skipping embedding generation"
            )
            return 0

        client = create_embeddings_client(embeddings_config)
        if not client:
            return 0

        worker = EmbeddingsSyncWorker(
            client=client,
            database=state.database,
            folders=folders,
            batch_size=50,
        )

        total = await worker.sync_all_folders()
        if total > 0:
            logger.debug(f"Generated embeddings for {total} emails")
        return total

    except Exception as e:
        logger.error(f"Embedding generation error: {e}")
        raise


async def embed_specific_uids(folder: str, uids: list[int]) -> int:
    """Embed exactly the specified UIDs. Used for lockstep sync+embed."""
    if not uids or not state.database or not state.database.supports_embeddings():
        return 0

    if not state.config or not state.config.database.embeddings:
        return 0

    embeddings_config = state.config.database.embeddings
    if not embeddings_config.enabled:
        return 0

    try:
        from workspace_secretary.engine.embeddings import create_embeddings_client

        client = create_embeddings_client(embeddings_config)
        if not client:
            return 0

        emails = state.database.get_emails_by_uids(uids, folder)
        if not emails:
            return 0

        results = await client.embed_emails(emails)

        stored = 0
        for email, result in zip(emails, results):
            if result.embedding:
                state.database.upsert_embedding(
                    uid=email["uid"],
                    folder=folder,
                    embedding=result.embedding,
                    model=result.model,
                    content_hash=result.content_hash,
                )
                stored += 1

        await client.close()
        return stored

    except Exception as e:
        logger.error(f"Embed specific UIDs error: {e}")
        return 0


async def initial_lockstep_sync_and_embed():
    """Initial sync: sync batch → embed batch → repeat until done."""
    if not state.database or not state.config:
        return

    folders = state.config.allowed_folders or ["INBOX"]
    loop = asyncio.get_running_loop()
    batch_size = 50
    supports_embeddings = state.database.supports_embeddings()

    if state._pool_init_lock is None:
        state._pool_init_lock = asyncio.Lock()

    if state._imap_pool_size == 0:
        async with state._pool_init_lock:
            if state._imap_pool_size == 0:
                logger.info("Initializing IMAP connection pool for lockstep sync...")
                await loop.run_in_executor(None, _init_connection_pool)

    if state._imap_pool_size == 0:
        logger.error("No IMAP connections available for lockstep sync")
        return

    total_synced = 0
    total_embedded = 0

    for folder in folders:
        folder_synced = 0
        folder_embedded = 0

        db_count = state.database.count_emails(folder)

        def _get_folder_count():
            try:
                client = state._imap_pool.get(timeout=60)
            except Empty:
                return 0
            try:
                info = client.select_folder(folder, readonly=True)
                return info.get("exists", 0)
            finally:
                state._imap_pool.put(client)

        folder_total = await loop.run_in_executor(
            state._sync_executor, _get_folder_count
        )

        remaining = folder_total - db_count
        if remaining <= 0:
            logger.info(
                f"[{folder}] Already fully synced ({db_count}/{folder_total} emails)"
            )
            continue

        logger.info(
            f"[{folder}] Resuming lockstep sync+embed ({db_count}/{folder_total} done, {remaining} remaining)..."
        )

        while state.running:

            def _sync_batch():
                try:
                    client = state._imap_pool.get(timeout=60)
                except Empty:
                    return [], False
                try:
                    return _sync_next_batch(client, folder, batch_size)
                finally:
                    state._imap_pool.put(client)

            synced_uids, has_more = await loop.run_in_executor(
                state._sync_executor, _sync_batch
            )

            if not synced_uids:
                break

            folder_synced += len(synced_uids)
            total_done = db_count + folder_synced
            pct = (total_done / folder_total * 100) if folder_total > 0 else 0
            logger.info(f"[{folder}] Synced {total_done}/{folder_total} ({pct:.1f}%)")

            if supports_embeddings:
                embedded = await embed_specific_uids(folder, synced_uids)
                folder_embedded += embedded

            if not has_more:
                break

        total_synced += folder_synced
        total_embedded += folder_embedded
        logger.info(
            f"[{folder}] Complete: {folder_synced} synced, {folder_embedded} embedded"
        )

    logger.info(
        f"Lockstep sync complete: {total_synced} synced, {total_embedded} embedded across {len(folders)} folders"
    )


def _idle_worker(
    client: ImapClient,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
):
    """Dedicated thread worker for IMAP IDLE operations.

    Runs the entire IDLE loop on a separate thread to avoid blocking
    the asyncio event loop. Communicates back via thread-safe event loop
    scheduling when a sync is needed.
    """
    idle_timeout = 25 * 60  # 25 minutes (Gmail requires re-IDLE every 29 min)
    logger.info("IDLE worker thread started")

    while not stop_event.is_set():
        try:
            client.select_folder("INBOX", readonly=True)
            client.idle_start()

            try:
                # This blocks for up to idle_timeout seconds
                responses = client.idle_check(timeout=idle_timeout)

                if responses:
                    for response in responses:
                        if len(response) >= 2 and response[1] in (
                            b"EXISTS",
                            b"EXPUNGE",
                        ):
                            logger.debug(f"IDLE notification: {response}")
                            # Schedule sync on the main event loop (thread-safe)
                            loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(debounced_sync())
                            )
                            break
            finally:
                client.idle_done()

        except Exception as e:
            logger.error(f"IDLE worker error: {e}")
            # Sleep before retry, but check stop_event periodically
            for _ in range(30):
                if stop_event.is_set():
                    break
                stop_event.wait(1.0)

    logger.info("IDLE worker thread stopped")


async def idle_monitor():
    """Background task that manages the IDLE worker thread.

    Monitors INBOX for changes and triggers sync when new mail arrives.
    Uses a dedicated IMAP connection and runs on a separate thread
    to avoid blocking the asyncio event loop.
    """
    if not state.config or not state.idle_client:
        return

    client = state.idle_client

    if not client.has_idle_capability():
        logger.info("Server does not support IDLE, skipping idle monitor")
        return

    logger.info("Starting IDLE monitor for push notifications")

    loop = asyncio.get_event_loop()
    stop_event = threading.Event()

    # Start the IDLE worker on a dedicated thread
    idle_thread = threading.Thread(
        target=_idle_worker,
        args=(client, loop, stop_event),
        name="idle-worker",
        daemon=True,
    )
    idle_thread.start()

    # Wait until we should stop
    try:
        while state.running and state.enrolled:
            await asyncio.sleep(1.0)
    finally:
        # Signal the worker thread to stop
        logger.info("Stopping IDLE worker thread...")
        stop_event.set()
        idle_thread.join(timeout=5.0)
        if idle_thread.is_alive():
            logger.warning("IDLE worker thread did not stop cleanly")


async def debounced_sync():
    """Trigger a sync with debouncing to batch rapid changes.

    If called multiple times within the debounce window, only one sync runs.
    """
    if state._sync_debounce_task and not state._sync_debounce_task.done():
        state._sync_debounce_task.cancel()
        try:
            await state._sync_debounce_task
        except asyncio.CancelledError:
            pass

    async def _delayed_sync():
        await asyncio.sleep(state._sync_debounce_delay)
        await sync_emails_parallel()

    state._sync_debounce_task = asyncio.create_task(_delayed_sync())


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


@app.get("/health")
async def health():
    return {
        "service": "secretary-engine",
        "health": "healthy" if state.running else "stopped",
    }


@app.post("/api/enroll")
async def trigger_enroll():
    """Trigger enrollment attempt. Called by auth_setup after saving credentials."""
    if state.enrolled:
        return {"status": "ok", "message": "Already enrolled", "enrolled": True}

    if state.enrollment_task:
        state.enrollment_task.cancel()
        try:
            await state.enrollment_task
        except asyncio.CancelledError:
            pass
        state.enrollment_task = None

    success = await try_enroll()
    if success:
        logger.info("Enrollment triggered successfully, starting sync loop")
        state.sync_task = asyncio.create_task(sync_loop())
        return {"status": "ok", "message": "Enrollment successful", "enrolled": True}

    state.enrollment_task = asyncio.create_task(enrollment_watch_loop())
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=state.enrollment_error or "Enrollment failed",
    )


# ============================================================================
# Sync endpoints
# ============================================================================


@app.post("/api/sync/trigger")
async def trigger_sync():
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database or not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Engine not ready",
        )

    try:
        asyncio.create_task(sync_emails_parallel())
        return {"status": "ok", "message": "Sync queued"}
    except Exception:
        logger.exception("Sync trigger failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger sync",
        )


# ============================================================================
# Email mutation endpoints
# ============================================================================


@app.post("/api/email/move")
async def move_email(req: EmailMoveRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        state.imap_client.move_email(req.uid, req.folder, req.destination)
        if state.database:
            state.database.delete_email(req.uid, req.folder)
        await debounced_sync()
        return {"status": "ok"}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP move error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP move failed: {e}",
        )
    except Exception as e:
        logger.exception("Unexpected move_email error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to move email",
        )


@app.post("/api/email/mark-read")
async def mark_read(req: EmailMarkRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        state.imap_client.mark_email(req.uid, req.folder, "read")
        if state.database:
            state.database.mark_email_read(req.uid, req.folder, True)
        return {"status": "ok"}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP mark-read error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP mark-read failed: {e}",
        )
    except Exception:
        logger.exception("Unexpected mark_read error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark email as read",
        )


@app.post("/api/email/mark-unread")
async def mark_unread(req: EmailMarkRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        state.imap_client.mark_email(req.uid, req.folder, "unread")
        if state.database:
            state.database.mark_email_read(req.uid, req.folder, False)
        return {"status": "ok"}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP mark-unread error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP mark-unread failed: {e}",
        )
    except Exception:
        logger.exception("Unexpected mark_unread error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark email as unread",
        )


@app.post("/api/email/labels")
async def modify_labels(req: EmailLabelsRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        if req.action == "add":
            state.imap_client.add_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "remove":
            state.imap_client.remove_gmail_labels(req.uid, req.folder, req.labels)
        elif req.action == "set":
            state.imap_client.set_gmail_labels(req.uid, req.folder, req.labels)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid action: {req.action}",
            )

        await debounced_sync()
        return {"status": "ok"}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP label modification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP label modification failed: {e}",
        )
    except Exception:
        logger.exception("Unexpected modify_labels error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to modify labels",
        )


@app.post("/api/email/send")
async def send_email(req: SendEmailRequest):
    """Send an email via SMTP."""
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not loaded",
        )

    if not state.config.imap.oauth2:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="OAuth2 configuration required for SMTP sending",
        )

    try:
        message = EmailMessage()
        message_id = make_msgid()
        message["Message-ID"] = message_id
        message["From"] = state.config.imap.username
        message["To"] = ", ".join(req.to)
        message["Subject"] = req.subject

        if req.cc:
            message["Cc"] = ", ".join(req.cc)

        if req.reply_to_message_id:
            message["In-Reply-To"] = req.reply_to_message_id
            message["References"] = req.reply_to_message_id

        message.set_content(req.body or "", subtype="plain")

        if req.bcc:
            message["Bcc"] = ", ".join(req.bcc)

        smtp_client = SMTPClient(state.config)
        smtp_client.send_message(message)

        if "Bcc" in message:
            del message["Bcc"]

        await debounced_sync()
        return {"status": "ok", "message_id": message_id}

    except Exception:
        logger.exception("Send email error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email",
        )


@app.post("/api/email/draft-reply")
async def create_draft_reply(req: DraftReplyRequest):
    """Create a draft reply to an email."""
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database or not state.config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Engine not ready",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IMAP client not connected",
        )

    try:
        original = state.database.get_email_by_uid(req.uid, req.folder)
        if not original:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original email not found",
            )

        reply_to = original.get("reply_to") or original.get("from_addr", "")
        recipients = [reply_to] if reply_to else []
        user_email = state.config.imap.username.lower()

        if req.reply_all:
            to_addrs = original.get("to_addr", []) or []
            if isinstance(to_addrs, str):
                to_addrs = [to_addrs]
            cc_addrs = original.get("cc_addr", []) or []
            if isinstance(cc_addrs, str):
                cc_addrs = [cc_addrs]
            for addr in to_addrs + cc_addrs:
                normalized = addr.lower()
                if normalized != user_email and addr not in recipients:
                    recipients.append(addr)

        # Build subject
        subject = original.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        message = EmailMessage()
        message_id = make_msgid()
        message["Message-ID"] = message_id
        message["Subject"] = subject
        message["From"] = state.config.imap.username
        message["To"] = ", ".join(recipients)

        original_msg_id = original.get("message_id", "")
        if original_msg_id:
            message["In-Reply-To"] = original_msg_id
            message["References"] = original_msg_id

        message.set_content(req.body or "", subtype="plain")

        if req.reply_all and original.get("cc_addr"):
            cc_addrs = original.get("cc_addr", [])
            if isinstance(cc_addrs, str):
                cc_addrs = [cc_addrs]
            cc_addrs = [addr for addr in cc_addrs if addr.lower() != user_email]
            if cc_addrs:
                message["Cc"] = ", ".join(cc_addrs)

        draft_uid = state.imap_client.save_draft_mime(message)
        await debounced_sync()

        return {
            "status": "ok",
            "draft_uid": draft_uid,
            "recipients": recipients,
            "subject": subject,
            "message_id": message_id,
        }

    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP draft save error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP save draft failed: {e}",
        )
    except Exception:
        logger.exception("Create draft error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create draft reply",
        )


@app.post("/api/email/setup-labels")
async def setup_labels(req: SetupLabelsRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.config:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not loaded",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IMAP client not connected",
        )

    created: list[str] = []
    already_exists: list[str] = []
    failed: list[str] = []

    try:
        folders = set(state.imap_client.list_folders(refresh=True))

        for label_name in SECRETARY_LABELS:
            if label_name in folders:
                already_exists.append(label_name)
                continue

            if req.dry_run:
                created.append(f"{label_name} (would create)")
                continue

            if state.imap_client.create_folder(label_name):
                created.append(label_name)
            else:
                logger.warning(f"Failed to create label '{label_name}'")
                failed.append(label_name)

        await debounced_sync()
        return {
            "status": "ok",
            "dry_run": req.dry_run,
            "created": created,
            "already_exists": already_exists,
            "failed": failed,
        }

    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"Setup labels IMAP error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP setup labels failed: {e}",
        )
    except Exception:
        logger.exception("Setup labels error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to setup labels",
        )


@app.get("/api/email/{folder}/{uid}/attachment/{filename}")
async def download_attachment(folder: str, uid: int, filename: str):
    """Download an email attachment."""
    if not state.enrolled:
        raise HTTPException(status_code=401, detail="No account configured")

    if not state.imap_client:
        raise HTTPException(status_code=500, detail="IMAP client not connected")

    try:
        email = state.imap_client.fetch_email(uid, folder)
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        if not email.attachments:
            raise HTTPException(status_code=404, detail="No attachments found")

        attachment = next(
            (att for att in email.attachments if att.filename == filename), None
        )
        if not attachment:
            raise HTTPException(
                status_code=404, detail=f"Attachment '{filename}' not found"
            )

        if not attachment.content:
            raise HTTPException(status_code=500, detail="Attachment content is empty")

        return StreamingResponse(
            io.BytesIO(attachment.content),
            media_type=attachment.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{attachment.filename}"'
            },
        )
        if not attachment:
            raise HTTPException(
                status_code=404, detail=f"Attachment '{filename}' not found"
            )

        return StreamingResponse(
            io.BytesIO(attachment.content),
            media_type=attachment.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{attachment.filename}"'
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download attachment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Calendar endpoints
# ============================================================================


def _get_selected_calendar_ids(db: DatabaseInterface) -> list[str]:
    prefs = db.get_user_preferences("default")
    return prefs.get("calendar", {}).get("selected_calendar_ids", ["primary"])


def _get_calendar_sync_metadata(db: DatabaseInterface, calendar_ids: list[str]) -> dict:
    from datetime import datetime

    states = [db.get_calendar_sync_state(cid) for cid in calendar_ids]
    last_sync_values = []
    for s in states:
        if s and s.get("last_incremental_sync_at"):
            last_sync_values.append(s["last_incremental_sync_at"])

    last_sync = min(last_sync_values) if last_sync_values else None

    outbox = db.list_calendar_outbox(statuses=["pending", "conflict"])
    pending_count = sum(1 for op in outbox if op["status"] == "pending")
    conflict_count = sum(1 for op in outbox if op["status"] == "conflict")

    is_stale = True
    if last_sync:
        try:
            if isinstance(last_sync, str):
                from dateutil import parser as dateutil_parser

                last_sync_dt = dateutil_parser.parse(last_sync)
            else:
                last_sync_dt = last_sync
            is_stale = (
                datetime.utcnow().replace(tzinfo=None)
                - last_sync_dt.replace(tzinfo=None)
            ).total_seconds() > 120
        except:
            is_stale = True

    return {
        "last_sync": str(last_sync) if last_sync else None,
        "pending_count": pending_count,
        "conflict_count": conflict_count,
        "is_stale": is_stale,
    }


@app.get("/api/calendar/events")
async def list_calendar_events(
    time_min: Optional[str] = Query(None, description="Start time (ISO format)"),
    time_max: Optional[str] = Query(None, description="End time (ISO format)"),
    calendar_id: str = Query("primary", description="Calendar ID"),
):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    try:
        if not time_min:
            time_min = datetime.utcnow().isoformat() + "Z"
        if not time_max:
            time_max = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

        selected_ids = _get_selected_calendar_ids(state.database)

        events = state.database.query_calendar_events_cached(
            selected_ids, time_min, time_max
        )

        metadata = _get_calendar_sync_metadata(state.database, selected_ids)

        return {
            "status": "ok",
            "events": events,
            "metadata": metadata,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("List calendar events error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list events",
        )


@app.post("/api/calendar/availability")
async def get_calendar_availability(
    req: FreeBusyRequest,
):
    """Get free/busy information for the user's selected calendars."""
    if not req.calendar_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="calendar_ids is required when calling this endpoint",
        )
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    calendar_ids = req.calendar_ids
    if not calendar_ids and state.database:
        calendar_ids = _get_selected_calendar_ids(state.database)

    try:
        availability = state.calendar_client.get_availability(
            req.time_min, req.time_max, calendar_ids
        )
        return {"status": "ok", "availability": availability}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Get availability error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch availability",
        )


@app.post("/api/calendar/event")
async def create_calendar_event(req: CalendarEventRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

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

    if req.meeting_type == "google_meet":
        import uuid as uuid_lib

        event_data["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid_lib.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    try:
        local_temp_id = f"local:{uuid.uuid4()}"

        outbox_id = state.database.enqueue_calendar_outbox(
            op_type="create",
            calendar_id=req.calendar_id,
            payload_json=event_data,
            local_temp_id=local_temp_id,
        )

        from dateutil import parser as dateutil_parser

        start_dt = dateutil_parser.parse(req.start_time)
        end_dt = dateutil_parser.parse(req.end_time)

        state.database.upsert_calendar_event_cache(
            calendar_id=req.calendar_id,
            event_id=local_temp_id,
            raw_json=event_data,
            start_ts_utc=start_dt.isoformat(),
            end_ts_utc=end_dt.isoformat(),
            summary=req.summary,
            location=req.location,
            local_status="pending",
        )

        return {
            "status": "queued",
            "event_id": local_temp_id,
            "outbox_id": outbox_id,
            "pending": True,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Create calendar event error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue calendar event",
        )


@app.post("/api/calendar/respond")
async def respond_to_meeting(req: MeetingResponseRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    try:
        event = (
            state.calendar_client.service.events()
            .get(calendarId=req.calendar_id, eventId=req.event_id)
            .execute()
        )

        user_email = state.config.imap.username if state.config else None
        if not user_email:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User email not configured",
            )

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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Respond to meeting error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to respond to meeting",
        )


@app.get("/api/calendar/list")
async def list_calendars():
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    try:
        calendars = state.calendar_client.list_calendars()

        if state.database:
            selected_ids = _get_selected_calendar_ids(state.database)
            for cal in calendars:
                cal["selected"] = cal.get("id") in selected_ids

        return {"status": "ok", "calendars": calendars}
    except HTTPException:
        raise
    except Exception:
        logger.exception("List calendars error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list calendars",
        )


@app.get("/api/calendar/{calendar_id}")
async def get_calendar(calendar_id: str):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    try:
        calendar = state.calendar_client.get_calendar(calendar_id)
        return {"status": "ok", "calendar": calendar}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Get calendar error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch calendar",
        )


@app.get("/api/calendar/{calendar_id}/events/{event_id}")
async def get_calendar_event(calendar_id: str, event_id: str):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    try:
        event = state.calendar_client.get_event(calendar_id, event_id)
        return {"status": "ok", "event": event}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Get calendar event error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch calendar event",
        )


class CalendarEventUpdateRequest(BaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    attendees: Optional[list[str]] = None


@app.patch("/api/calendar/{calendar_id}/events/{event_id}")
async def update_calendar_event(
    calendar_id: str, event_id: str, req: CalendarEventUpdateRequest
):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    if event_id.startswith("local:"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update event that has not been synced yet",
        )

    event_data: dict[str, Any] = {}
    if req.summary is not None:
        event_data["summary"] = req.summary
    if req.description is not None:
        event_data["description"] = req.description
    if req.location is not None:
        event_data["location"] = req.location
    if req.start_time is not None:
        event_data["start"] = {"dateTime": req.start_time}
    if req.end_time is not None:
        event_data["end"] = {"dateTime": req.end_time}
    if req.attendees is not None:
        event_data["attendees"] = [{"email": email} for email in req.attendees]

    try:
        outbox_id = state.database.enqueue_calendar_outbox(
            op_type="patch",
            calendar_id=calendar_id,
            payload_json=event_data,
            event_id=event_id,
        )

        cached = state.database.query_calendar_events_cached(
            [calendar_id], "1970-01-01T00:00:00Z", "2100-01-01T00:00:00Z"
        )
        existing_event = next((e for e in cached if e.get("id") == event_id), None)

        if existing_event:
            if req.summary:
                existing_event["summary"] = req.summary
            if req.start_time:
                existing_event["start"] = {"dateTime": req.start_time}
            if req.end_time:
                existing_event["end"] = {"dateTime": req.end_time}

            from dateutil import parser as dateutil_parser

            start_dt = dateutil_parser.parse(
                existing_event["start"].get("dateTime", "")
            )
            end_dt = dateutil_parser.parse(existing_event["end"].get("dateTime", ""))

            state.database.upsert_calendar_event_cache(
                calendar_id=calendar_id,
                event_id=event_id,
                raw_json=existing_event,
                start_ts_utc=start_dt.isoformat(),
                end_ts_utc=end_dt.isoformat(),
                summary=existing_event.get("summary"),
                location=existing_event.get("location"),
                local_status="pending",
            )

        return {"status": "queued", "outbox_id": outbox_id, "pending": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Update calendar event error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue calendar event update",
        )


@app.delete("/api/calendar/{calendar_id}/events/{event_id}")
async def delete_calendar_event(calendar_id: str, event_id: str):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    try:
        outbox_id = state.database.enqueue_calendar_outbox(
            op_type="delete",
            calendar_id=calendar_id,
            payload_json={},
            event_id=event_id,
        )

        cached = state.database.query_calendar_events_cached(
            [calendar_id], "1970-01-01T00:00:00Z", "2100-01-01T00:00:00Z"
        )
        existing_event = next((e for e in cached if e.get("id") == event_id), None)

        if existing_event:
            existing_event["status"] = "cancelled"

            from dateutil import parser as dateutil_parser

            start_dt = dateutil_parser.parse(
                existing_event["start"].get(
                    "dateTime", existing_event["start"].get("date", "")
                )
            )
            end_dt = dateutil_parser.parse(
                existing_event["end"].get(
                    "dateTime", existing_event["end"].get("date", "")
                )
            )

            state.database.upsert_calendar_event_cache(
                calendar_id=calendar_id,
                event_id=event_id,
                raw_json=existing_event,
                status="cancelled",
                start_ts_utc=start_dt.isoformat()
                if existing_event["start"].get("dateTime")
                else None,
                end_ts_utc=end_dt.isoformat()
                if existing_event["end"].get("dateTime")
                else None,
                start_date=existing_event["start"].get("date"),
                end_date=existing_event["end"].get("date"),
                is_all_day=bool(existing_event["start"].get("date")),
                summary=existing_event.get("summary"),
                location=existing_event.get("location"),
                local_status="pending",
            )

        return {"status": "queued", "outbox_id": outbox_id, "pending": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Delete calendar event error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue calendar event deletion",
        )


class FreeBusyRequest(BaseModel):
    time_min: str
    time_max: str
    calendar_ids: Optional[list[str]] = None


@app.post("/api/calendar/freebusy")
async def freebusy_query(req: FreeBusyRequest):
    if not req.calendar_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="calendar_ids is required when calling this endpoint",
        )

    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.calendar_client or not state.calendar_client.service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar not connected",
        )

    try:
        result = state.calendar_client.freebusy_query(
            req.time_min, req.time_max, req.calendar_ids
        )
        return {"status": "ok", "freebusy": result}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Freebusy query error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query free/busy",
        )


def run_engine():
    import argparse

    parser = argparse.ArgumentParser(description="Gmail Secretary Engine API")
    parser.add_argument(
        "--host", type=str, default=None, help="TCP host to bind to (e.g., 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="TCP port to bind to (e.g., 8001)"
    )
    args = parser.parse_args()

    if args.host and args.port:
        logger.info(f"Starting Engine API on TCP {args.host}:{args.port}")
        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
    else:
        if Path(SOCKET_PATH).exists():
            Path(SOCKET_PATH).unlink()
        logger.info(f"Starting Engine API on Unix socket {SOCKET_PATH}")
        config = uvicorn.Config(
            app,
            uds=SOCKET_PATH,
            log_level="info",
        )

    server = uvicorn.Server(config)
    server.run()


# =============================================================================
# INTERNAL-ONLY ENDPOINTS (Web UI only, NOT exposed to MCP)
# =============================================================================


class EmailDeleteRequest(BaseModel):
    uid: int
    folder: str


@app.post("/api/internal/email/delete")
async def internal_delete_email(req: EmailDeleteRequest):
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        state.imap_client.move_email(req.uid, req.folder, "[Gmail]/Trash")
        return {"status": "ok", "message": f"Email {req.uid} moved to Trash"}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP delete error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP delete failed: {e}",
        )
    except Exception:
        logger.exception("Unexpected internal_delete_email error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete email",
        )


@app.get("/api/internal/folders")
async def internal_list_folders():
    if not state.enrolled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account configured. Run auth_setup to add an account.",
        )

    if not state.imap_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="IMAP not connected",
        )

    try:
        folders = state.imap_client.list_folders()
        return {"status": "ok", "folders": folders}
    except HTTPException:
        raise
    except imapclient.IMAPClient.Error as e:  # type: ignore[attr-defined]
        logger.error(f"IMAP list folders error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP list folders failed: {e}",
        )
    except Exception:
        logger.exception("Unexpected internal_list_folders error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list folders",
        )


@app.get("/api/internal/labels")
async def internal_list_labels():
    labels = SECRETARY_LABELS + [
        "INBOX",
        "STARRED",
        "IMPORTANT",
        "SENT",
        "DRAFTS",
        "SPAM",
        "TRASH",
    ]
    return {"status": "ok", "labels": labels}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_engine()
