"""MCP tools - reads from database, mutations via Engine API.

Architecture:
- Read operations: Direct database queries (SQLite or PostgreSQL)
- Mutations: Engine API calls via EngineClient
- No direct IMAP/Gmail/Calendar client access
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context

from workspace_secretary.config import ServerConfig
from workspace_secretary.engine.database import DatabaseInterface
from workspace_secretary.engine_client import EngineClient

logger = logging.getLogger(__name__)


def _get_database(ctx: Context) -> DatabaseInterface:
    """Get database from context."""
    db = ctx.request_context.lifespan_context.get("database")
    if not db:
        raise RuntimeError("Database not available. Engine may still be syncing.")
    return db


def _get_engine(ctx: Context) -> EngineClient:
    """Get engine client from context."""
    engine = ctx.request_context.lifespan_context.get("engine_client")
    if not engine:
        raise RuntimeError("Engine client not available.")
    return engine


def _get_config(ctx: Context) -> ServerConfig:
    """Get server config from context."""
    config = ctx.request_context.lifespan_context.get("config")
    if not config:
        raise RuntimeError("Configuration not available.")
    return config


def _get_embeddings_client(ctx: Context):
    """Get embeddings client from context (may be None)."""
    return ctx.request_context.lifespan_context.get("embeddings_client")


def _format_email_summary(email: Dict[str, Any]) -> Dict[str, Any]:
    """Format email dict for API response."""
    flags = email.get("flags", "").split(",") if email.get("flags") else []
    return {
        "uid": email.get("uid"),
        "folder": email.get("folder"),
        "from": email.get("from_addr"),
        "to": email.get("to_addr"),
        "cc": email.get("cc_addr"),
        "subject": email.get("subject"),
        "date": email.get("date"),
        "is_unread": email.get("is_unread", False),
        "flags": flags,
    }


def _format_email_detail(email: Dict[str, Any]) -> Dict[str, Any]:
    """Format email dict with full details."""
    base = _format_email_summary(email)
    base.update(
        {
            "message_id": email.get("message_id"),
            "in_reply_to": email.get("in_reply_to"),
            "references": email.get("references"),
            "body": email.get("body_text") or email.get("body_html") or "",
            "body_html": email.get("body_html"),
        }
    )
    return base


def register_tools(
    mcp: FastMCP,
    config: ServerConfig,
    enable_semantic_search: bool = False,
) -> None:
    """Register all MCP tools.

    Args:
        mcp: FastMCP server instance
        config: Server configuration
        enable_semantic_search: Whether semantic search is available
    """

    # ============================================================
    # READ-ONLY TOOLS (Database queries)
    # ============================================================

    @mcp.tool()
    async def list_folders(ctx: Context) -> str:
        """List all synced email folders.

        Returns:
            JSON list of folder information
        """
        try:
            db = _get_database(ctx)
            folders = db.get_synced_folders()
            return json.dumps(folders, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error listing folders: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def search_emails(
        folder: str = "INBOX",
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 50,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Search emails in the database.

        Args:
            folder: Folder to search in
            from_addr: Filter by sender address (partial match)
            to_addr: Filter by recipient address (partial match)
            subject: Filter by subject (partial match)
            body: Filter by body content (partial match)
            unread_only: Only return unread emails
            limit: Maximum results to return
            ctx: MCP context

        Returns:
            JSON list of matching emails
        """
        try:
            db = _get_database(ctx)
            emails = db.search_emails(
                folder=folder,
                from_addr=from_addr,
                to_addr=to_addr,
                subject_contains=subject,
                body_contains=body,
                is_unread=True if unread_only else None,
                limit=limit,
            )
            results = [_format_email_summary(e) for e in emails]
            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_email_details(
        uid: int,
        folder: str = "INBOX",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get full details of a specific email.

        Args:
            uid: Email UID
            folder: Folder name
            ctx: MCP context

        Returns:
            JSON with email details including body
        """
        try:
            db = _get_database(ctx)
            email = db.get_email_by_uid(uid, folder)
            if not email:
                return json.dumps({"error": f"Email {uid} not found in {folder}"})
            return json.dumps(_format_email_detail(email), indent=2, default=str)
        except Exception as e:
            logger.error(f"Error getting email details: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_email_thread(
        uid: int,
        folder: str = "INBOX",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get all emails in a conversation thread.

        Args:
            uid: UID of an email in the thread
            folder: Folder name
            ctx: MCP context

        Returns:
            JSON list of emails in the thread, sorted by date
        """
        try:
            db = _get_database(ctx)
            thread_emails = db.get_thread_emails(uid, folder)
            if not thread_emails:
                # Fall back to single email
                email = db.get_email_by_uid(uid, folder)
                if email:
                    thread_emails = [email]
                else:
                    return json.dumps({"error": f"Email {uid} not found"})

            # Sort by date
            thread_emails.sort(key=lambda e: e.get("date") or "")

            results = []
            for email in thread_emails:
                result = _format_email_summary(email)
                result["snippet"] = (
                    email.get("body_text") or email.get("body_html") or ""
                )[:150]
                results.append(result)

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error getting email thread: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_unread_messages(
        folder: str = "INBOX",
        limit: int = 50,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get unread messages from a folder.

        Args:
            folder: Folder name
            limit: Maximum messages to return
            ctx: MCP context

        Returns:
            JSON list of unread emails
        """
        try:
            db = _get_database(ctx)
            emails = db.search_emails(folder=folder, is_unread=True, limit=limit)
            results = []
            for email in emails:
                result = _format_email_summary(email)
                result["snippet"] = (email.get("body_text") or "")[:100]
                results.append(result)
            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error getting unread messages: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def gmail_search(
        query: str,
        max_results: int = 20,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Search emails using Gmail-like syntax.

        Supports: from:, to:, subject:, is:unread, is:read

        Args:
            query: Gmail-style search query
            max_results: Maximum results
            ctx: MCP context

        Returns:
            JSON list of matching emails
        """
        try:
            db = _get_database(ctx)

            # Parse Gmail-style query
            is_unread = None
            from_addr = None
            to_addr = None
            subject_contains = None

            query_lower = query.lower()
            if "is:unread" in query_lower:
                is_unread = True
            if "is:read" in query_lower:
                is_unread = False

            from_match = re.search(r"from:(\S+)", query_lower)
            if from_match:
                from_addr = from_match.group(1)

            to_match = re.search(r"to:(\S+)", query_lower)
            if to_match:
                to_addr = to_match.group(1)

            subject_match = re.search(
                r'subject:(["\']?)(.+?)\1(?:\s|$)', query, re.IGNORECASE
            )
            if subject_match:
                subject_contains = subject_match.group(2)

            emails = db.search_emails(
                folder="INBOX",
                from_addr=from_addr,
                to_addr=to_addr,
                subject_contains=subject_contains,
                is_unread=is_unread,
                limit=max_results,
            )

            results = [_format_email_summary(e) for e in emails]
            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error in gmail_search: {e}")
            return json.dumps({"error": str(e)})

    # ============================================================
    # MUTATION TOOLS (Engine API calls)
    # ============================================================

    @mcp.tool()
    async def mark_as_read(
        uid: int,
        folder: str = "INBOX",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Mark an email as read.

        Args:
            uid: Email UID
            folder: Folder name
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            result = engine.mark_read(uid, folder)
            if result.get("status") == "ok":
                return f"Email {uid} marked as read"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error marking as read: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def mark_as_unread(
        uid: int,
        folder: str = "INBOX",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Mark an email as unread.

        Args:
            uid: Email UID
            folder: Folder name
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            result = engine.mark_unread(uid, folder)
            if result.get("status") == "ok":
                return f"Email {uid} marked as unread"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error marking as unread: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def move_email(
        uid: int,
        folder: str,
        target_folder: str,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Move an email to another folder.

        Args:
            uid: Email UID
            folder: Source folder
            target_folder: Destination folder
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            result = engine.move_email(uid, folder, target_folder)
            if result.get("status") == "ok":
                return f"Email {uid} moved from {folder} to {target_folder}"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error moving email: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def modify_gmail_labels(
        uid: int,
        folder: str = "INBOX",
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Add or remove Gmail labels from an email.

        Args:
            uid: Email UID
            folder: Folder name
            add_labels: Labels to add
            remove_labels: Labels to remove
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            results = []

            if add_labels:
                result = engine.modify_labels(uid, folder, add_labels, "add")
                if result.get("status") == "ok":
                    results.append(f"Added: {', '.join(add_labels)}")
                else:
                    results.append(f"Failed to add labels: {result.get('message')}")

            if remove_labels:
                result = engine.modify_labels(uid, folder, remove_labels, "remove")
                if result.get("status") == "ok":
                    results.append(f"Removed: {', '.join(remove_labels)}")
                else:
                    results.append(f"Failed to remove labels: {result.get('message')}")

            if not results:
                return "No label changes requested"

            return "; ".join(results)
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error modifying labels: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def process_email(
        uid: int,
        folder: str,
        action: str,
        target_folder: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Process an email with a specific action.

        Args:
            uid: Email UID
            folder: Source folder
            action: Action (move, read, unread, delete)
            target_folder: Target folder for move action
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            action_lower = action.lower()

            if action_lower == "move":
                if not target_folder:
                    return "Target folder required for move action"
                result = engine.move_email(uid, folder, target_folder)
            elif action_lower == "read":
                result = engine.mark_read(uid, folder)
            elif action_lower == "unread":
                result = engine.mark_unread(uid, folder)
            elif action_lower == "delete":
                # Move to trash
                result = engine.move_email(uid, folder, "[Gmail]/Trash")
            else:
                return f"Invalid action: {action}. Use: move, read, unread, delete"

            if result.get("status") == "ok":
                return f"Action '{action}' completed on email {uid}"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            return f"Error: {e}"

    # ============================================================
    # CALENDAR TOOLS (Engine API calls)
    # ============================================================

    @mcp.tool()
    async def list_calendar_events(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """List calendar events in a time range.

        Args:
            time_min: Start time (ISO format, e.g., 2024-01-01T00:00:00Z)
            time_max: End time (ISO format)
            calendar_id: Calendar ID
            ctx: MCP context

        Returns:
            JSON list of events
        """
        try:
            engine = _get_engine(ctx)
            result = engine.list_calendar_events(time_min, time_max, calendar_id)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            return json.dumps(result.get("events", []), indent=2, default=str)
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error listing calendar events: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_calendar_availability(
        time_min: str,
        time_max: str,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Check free/busy status for a time range.

        Args:
            time_min: Start time (ISO format)
            time_max: End time (ISO format)
            ctx: MCP context

        Returns:
            JSON with availability information
        """
        try:
            engine = _get_engine(ctx)
            result = engine.get_calendar_availability(time_min, time_max)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            return json.dumps(result, indent=2, default=str)
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error getting availability: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_calendar_event(
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary",
        meeting_type: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Create a calendar event.

        Args:
            summary: Event title
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            description: Event description
            location: Event location
            calendar_id: Calendar ID
            meeting_type: 'google_meet' to add video conferencing
            ctx: MCP context

        Returns:
            JSON with created event details
        """
        try:
            engine = _get_engine(ctx)
            result = engine.create_calendar_event(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                calendar_id=calendar_id,
                meeting_type=meeting_type,
            )
            if result.get("status") == "ok":
                event = result.get("event", {})
                return json.dumps(
                    {
                        "status": "success",
                        "event_id": event.get("id"),
                        "html_link": event.get("htmlLink"),
                        "summary": event.get("summary"),
                    },
                    indent=2,
                )
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error creating calendar event: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def respond_to_meeting(
        event_id: str,
        calendar_id: str = "primary",
        response: str = "accepted",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Respond to a meeting invitation.

        Args:
            event_id: Calendar event ID
            calendar_id: Calendar ID
            response: Response (accepted, declined, tentative)
            ctx: MCP context

        Returns:
            Success or error message
        """
        if response not in ["accepted", "declined", "tentative"]:
            return f"Invalid response: {response}. Use: accepted, declined, tentative"

        try:
            engine = _get_engine(ctx)
            result = engine.respond_to_meeting(event_id, calendar_id, response)
            if result.get("status") == "ok":
                return f"Response '{response}' sent for event {event_id}"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error responding to meeting: {e}")
            return f"Error: {e}"

    # ============================================================
    # UTILITY TOOLS
    # ============================================================

    @mcp.tool()
    async def setup_smart_labels(
        dry_run: bool = False,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Setup Secretary folder hierarchy for organizing emails.

        Creates:
        - Secretary/Priority
        - Secretary/Action-Required
        - Secretary/Processed
        - Secretary/Calendar
        - Secretary/Newsletter
        - Secretary/Waiting

        Args:
            dry_run: If True, only report what would be created
            ctx: MCP context

        Returns:
            Status of folder creation
        """
        try:
            engine = _get_engine(ctx)
            result = engine.setup_labels(dry_run=dry_run)
            if result.get("status") == "ok":
                return "\n".join(result.get("results", ["Labels configured"]))
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error setting up labels: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def get_daily_briefing(
        date: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get daily briefing with calendar and priority emails.

        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            ctx: MCP context

        Returns:
            JSON with calendar events and email candidates with signals
        """
        from zoneinfo import ZoneInfo
        from datetime import time as dt_time

        try:
            db = _get_database(ctx)
            engine = _get_engine(ctx)
            config = _get_config(ctx)

            tz = ZoneInfo(config.timezone)
            vip_senders = set(config.vip_senders)
            identity = config.identity

            if date:
                target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
            else:
                target_date = datetime.now(tz)

            start_of_day = datetime.combine(target_date.date(), dt_time.min, tzinfo=tz)
            end_of_day = datetime.combine(target_date.date(), dt_time.max, tzinfo=tz)

            briefing: Dict[str, Any] = {
                "date": target_date.strftime("%Y-%m-%d"),
                "timezone": config.timezone,
                "calendar_events": [],
                "email_candidates": [],
            }

            # Get calendar events via Engine
            try:
                cal_result = engine.list_calendar_events(
                    start_of_day.isoformat(),
                    end_of_day.isoformat(),
                )
                if cal_result.get("status") != "no_account":
                    for event in cal_result.get("events", []):
                        briefing["calendar_events"].append(
                            {
                                "summary": event.get("summary"),
                                "start": event.get("start", {}).get("dateTime")
                                or event.get("start", {}).get("date"),
                                "end": event.get("end", {}).get("dateTime")
                                or event.get("end", {}).get("date"),
                                "location": event.get("location"),
                                "hangoutLink": event.get("hangoutLink"),
                            }
                        )
            except Exception as cal_err:
                logger.warning(f"Could not fetch calendar: {cal_err}")

            # Get unread emails from database
            emails = db.search_emails(folder="INBOX", is_unread=True, limit=50)

            for email in emails:
                sender = (email.get("from_addr") or "").lower()
                subject = (email.get("subject") or "").lower()
                body_text = email.get("body_text") or email.get("body_html") or ""
                snippet = body_text[:200].lower()

                to_addresses = [
                    addr.strip().lower()
                    for addr in (email.get("to_addr") or "").split(",")
                    if addr.strip()
                ]
                is_addressed_to_me = any(
                    identity.matches_email(addr) for addr in to_addresses
                )
                mentions_my_name = identity.matches_name(body_text)

                signals = {
                    "is_from_vip": any(vip in sender for vip in vip_senders),
                    "is_addressed_to_me": is_addressed_to_me,
                    "mentions_my_name": mentions_my_name,
                    "has_question": "?" in subject
                    or "?" in snippet
                    or bool(
                        re.search(r"\b(can you|could you|please|would you)\b", snippet)
                    ),
                    "mentions_deadline": bool(
                        re.search(
                            r"\b(eod|asap|urgent|deadline|due|by \w+day|by end of)\b",
                            snippet,
                        )
                    ),
                    "mentions_meeting": bool(
                        re.search(
                            r"\b(meet|meeting|schedule|calendar|invite|zoom|google meet|call)\b",
                            snippet,
                        )
                    ),
                }

                briefing["email_candidates"].append(
                    {
                        "uid": email.get("uid"),
                        "from": email.get("from_addr"),
                        "subject": email.get("subject"),
                        "date": email.get("date"),
                        "snippet": body_text[:150],
                        "signals": signals,
                    }
                )

            return json.dumps(briefing, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error generating daily briefing: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def send_email(
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Send an email.

        CRITICAL: This performs a mutation. Confirm content with user first.

        Args:
            to: Recipient email (comma-separated for multiple)
            subject: Email subject
            body: Email body (plain text)
            cc: CC recipients (comma-separated)
            ctx: MCP context

        Returns:
            Success or error message
        """
        try:
            engine = _get_engine(ctx)
            to_list = [addr.strip() for addr in to.split(",")]
            cc_list = [addr.strip() for addr in cc.split(",")] if cc else None

            result = engine.send_email(
                to=to_list,
                subject=subject,
                body=body,
                cc=cc_list,
            )
            if result.get("status") == "ok":
                return f"Email sent to {to}"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def create_draft_reply(
        uid: int,
        folder: str,
        reply_body: str,
        reply_all: bool = False,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Create a draft reply to an email.

        Args:
            uid: Original email UID
            folder: Folder containing original email
            reply_body: Reply content
            reply_all: Whether to reply to all recipients
            ctx: MCP context

        Returns:
            JSON with draft details
        """
        try:
            engine = _get_engine(ctx)
            result = engine.create_draft_reply(
                uid=uid,
                folder=folder,
                body=reply_body,
                reply_all=reply_all,
            )
            if result.get("status") == "ok":
                return json.dumps(
                    {
                        "status": "success",
                        "message": "Draft created",
                        "draft_uid": result.get("draft_uid"),
                        "draft_folder": result.get("draft_folder"),
                    },
                    indent=2,
                )
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error creating draft: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_task(
        description: str,
        priority: str = "medium",
        due_date: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Create a task in tasks.md file.

        Args:
            description: Task description
            priority: Priority (low, medium, high)
            due_date: Due date (YYYY-MM-DD)
            ctx: MCP context

        Returns:
            Success message
        """
        import os

        if not description:
            return "Error: Description is required"

        if priority not in ["low", "medium", "high"]:
            return f"Error: Invalid priority '{priority}'. Use: low, medium, high"

        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except ValueError:
                return f"Error: Invalid date format '{due_date}'. Use YYYY-MM-DD"

        task_entry = f"- [ ] {description} (Priority: {priority}"
        if due_date:
            task_entry += f", Due: {due_date}"
        task_entry += ")\n"

        tasks_file = os.path.join(os.getcwd(), "tasks.md")

        try:
            with open(tasks_file, "a") as f:
                f.write(task_entry)
            return f"Task created: {description}"
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def trigger_sync(ctx: Context = None) -> str:  # type: ignore
        """Trigger email sync in the engine.

        Returns:
            Sync status
        """
        try:
            engine = _get_engine(ctx)
            result = engine.trigger_sync()
            if result.get("status") == "ok":
                return "Sync triggered"
            elif result.get("status") == "no_account":
                return result.get("message", "No account configured")
            else:
                return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error triggering sync: {e}")
            return f"Error: {e}"

    # ============================================================
    # SEMANTIC SEARCH TOOLS (Conditional)
    # ============================================================

    if enable_semantic_search:

        @mcp.tool()
        async def semantic_search_emails(
            query: str,
            folder: str = "INBOX",
            limit: int = 20,
            ctx: Context = None,  # type: ignore
        ) -> str:
            """Search emails by meaning using AI embeddings.

            Args:
                query: Natural language query
                folder: Folder to search
                limit: Maximum results
                ctx: MCP context

            Returns:
                JSON list of semantically similar emails
            """
            try:
                db = _get_database(ctx)
                embeddings = _get_embeddings_client(ctx)

                if not embeddings:
                    return json.dumps({"error": "Embeddings not available"})

                if not db.supports_embeddings():
                    return json.dumps({"error": "Database does not support embeddings"})

                # Get query embedding
                result = await embeddings.embed_text(query)

                # Search
                emails = db.semantic_search(
                    query_embedding=result.embedding,
                    folder=folder,
                    limit=limit,
                )

                if not emails:
                    return json.dumps(
                        {"message": "No semantically similar emails found"}
                    )

                results = []
                for email in emails:
                    r = _format_email_summary(email)
                    r["similarity"] = round(email.get("similarity", 0), 3)
                    results.append(r)

                return json.dumps(results, indent=2, default=str)
            except Exception as e:
                logger.error(f"Error in semantic search: {e}")
                return json.dumps({"error": str(e)})

        @mcp.tool()
        async def find_related_emails(
            uid: int,
            folder: str = "INBOX",
            limit: int = 10,
            ctx: Context = None,  # type: ignore
        ) -> str:
            """Find emails similar to a specific email.

            Args:
                uid: Reference email UID
                folder: Folder name
                limit: Maximum results
                ctx: MCP context

            Returns:
                JSON list of similar emails
            """
            try:
                db = _get_database(ctx)

                if not db.supports_embeddings():
                    return json.dumps({"error": "Database does not support embeddings"})

                emails = db.find_similar_emails(uid, folder, limit)

                if not emails:
                    return json.dumps(
                        {"message": f"No similar emails found for UID {uid}"}
                    )

                results = []
                for email in emails:
                    r = _format_email_summary(email)
                    r["similarity"] = round(email.get("similarity", 0), 3)
                    results.append(r)

                return json.dumps(results, indent=2, default=str)
            except Exception as e:
                logger.error(f"Error finding related emails: {e}")
                return json.dumps({"error": str(e)})

    # ============================================================
    # BATCH OPERATION TOOLS (Time-boxed with continuation)
    # ============================================================

    @mcp.tool()
    async def quick_clean_inbox(
        continuation_state: Optional[str] = None,
        time_limit_seconds: int = 5,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Identify emails for cleanup (time-boxed operation).

        Finds emails where user is NOT in To/CC and name NOT mentioned.
        Safe for batch processing with continuation support.

        Args:
            continuation_state: State from previous call (for pagination)
            time_limit_seconds: Max time to process (default 5s)
            ctx: MCP context

        Returns:
            JSON with candidates and continuation state
        """
        import time

        try:
            db = _get_database(ctx)
            config = _get_config(ctx)
            identity = config.identity

            start_time = time.time()

            # Parse continuation state
            state = (
                json.loads(continuation_state)
                if continuation_state
                else {
                    "offset": 0,
                    "processed_uids": [],
                }
            )
            offset = state.get("offset", 0)
            processed_uids = set(state.get("processed_uids", []))

            # Fetch batch of emails
            emails = db.search_emails(folder="INBOX", limit=100)

            candidates = []
            new_processed = []

            for i, email in enumerate(emails[offset:]):
                # Check time limit
                if time.time() - start_time > time_limit_seconds:
                    return json.dumps(
                        {
                            "status": "partial",
                            "has_more": True,
                            "time_limit_reached": True,
                            "candidates": candidates,
                            "continuation_state": json.dumps(
                                {
                                    "offset": offset + i,
                                    "processed_uids": list(
                                        processed_uids | set(new_processed)
                                    ),
                                }
                            ),
                        },
                        indent=2,
                    )

                uid = email.get("uid")
                if uid in processed_uids:
                    continue

                new_processed.append(uid)

                # Check if user is in To/CC
                to_addr = (email.get("to_addr") or "").lower()
                cc_addr = (email.get("cc_addr") or "").lower()

                user_in_to = identity.matches_email(to_addr)
                user_in_cc = identity.matches_email(cc_addr)

                if user_in_to or user_in_cc:
                    continue  # Skip - user is directly addressed

                # Check if name mentioned in body
                body = email.get("body_text") or email.get("body_html") or ""
                if identity.matches_name(body):
                    continue  # Skip - user's name mentioned

                # This is a candidate for cleanup
                candidates.append(
                    {
                        "uid": uid,
                        "from": email.get("from_addr"),
                        "to": email.get("to_addr"),
                        "cc": email.get("cc_addr"),
                        "subject": email.get("subject"),
                        "date": email.get("date"),
                        "confidence": "high"
                        if not user_in_to and not user_in_cc
                        else "medium",
                    }
                )

            return json.dumps(
                {
                    "status": "complete",
                    "has_more": False,
                    "candidates": candidates,
                },
                indent=2,
                default=str,
            )

        except Exception as e:
            logger.error(f"Error in quick_clean_inbox: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def execute_clean_batch(
        uids: List[int],
        action: str = "archive",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Execute cleanup on approved emails.

        Args:
            uids: List of email UIDs to process
            action: Action to take (archive, mark_read, label)
            ctx: MCP context

        Returns:
            Processing result
        """
        try:
            engine = _get_engine(ctx)

            results = {"success": 0, "failed": 0, "errors": []}

            for uid in uids:
                try:
                    if action == "archive":
                        # Mark read and apply label
                        engine.mark_read(uid, "INBOX")
                        engine.modify_labels(
                            uid, "INBOX", ["Secretary/Auto-Cleaned"], "add"
                        )
                        engine.move_email(uid, "INBOX", "[Gmail]/All Mail")
                    elif action == "mark_read":
                        engine.mark_read(uid, "INBOX")
                    elif action == "label":
                        engine.modify_labels(
                            uid, "INBOX", ["Secretary/Auto-Cleaned"], "add"
                        )

                    results["success"] += 1
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append(f"UID {uid}: {e}")

            return json.dumps(results, indent=2)

        except ConnectionError:
            return "Engine not running. Start secretary-engine first."
        except Exception as e:
            logger.error(f"Error executing clean batch: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def triage_priority_emails(
        continuation_state: Optional[str] = None,
        time_limit_seconds: int = 5,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Identify high-priority emails for immediate attention.

        Priority criteria:
        - User in To: with <5 total recipients, OR
        - User in To: with <15 recipients AND name mentioned in body

        Args:
            continuation_state: State from previous call
            time_limit_seconds: Max processing time
            ctx: MCP context

        Returns:
            JSON with priority emails and their signals
        """
        import time

        try:
            db = _get_database(ctx)
            config = _get_config(ctx)
            identity = config.identity
            vip_senders = set(config.vip_senders)

            start_time = time.time()

            state = (
                json.loads(continuation_state)
                if continuation_state
                else {
                    "offset": 0,
                    "processed_uids": [],
                }
            )
            offset = state.get("offset", 0)
            processed_uids = set(state.get("processed_uids", []))

            emails = db.search_emails(folder="INBOX", is_unread=True, limit=100)

            priority_emails = []
            new_processed = []

            for i, email in enumerate(emails[offset:]):
                if time.time() - start_time > time_limit_seconds:
                    return json.dumps(
                        {
                            "status": "partial",
                            "has_more": True,
                            "priority_emails": priority_emails,
                            "continuation_state": json.dumps(
                                {
                                    "offset": offset + i,
                                    "processed_uids": list(
                                        processed_uids | set(new_processed)
                                    ),
                                }
                            ),
                        },
                        indent=2,
                    )

                uid = email.get("uid")
                if uid in processed_uids:
                    continue

                new_processed.append(uid)

                to_addr = (email.get("to_addr") or "").lower()
                cc_addr = (email.get("cc_addr") or "").lower()
                sender = (email.get("from_addr") or "").lower()
                body = email.get("body_text") or ""

                user_in_to = identity.matches_email(to_addr)

                if not user_in_to:
                    continue  # Must be in To: field

                # Count recipients
                to_count = len([a for a in to_addr.split(",") if a.strip()])
                cc_count = len([a for a in cc_addr.split(",") if a.strip()])
                total_recipients = to_count + cc_count

                name_mentioned = identity.matches_name(body)
                is_vip = any(vip in sender for vip in vip_senders)

                # Priority criteria
                is_priority = False
                if total_recipients < 5:
                    is_priority = True
                elif total_recipients < 15 and name_mentioned:
                    is_priority = True
                elif is_vip:
                    is_priority = True

                if is_priority:
                    priority_emails.append(
                        {
                            "uid": uid,
                            "from": email.get("from_addr"),
                            "to": email.get("to_addr"),
                            "subject": email.get("subject"),
                            "date": email.get("date"),
                            "snippet": body[:150],
                            "signals": {
                                "is_from_vip": is_vip,
                                "total_recipients": total_recipients,
                                "name_mentioned": name_mentioned,
                            },
                        }
                    )

            return json.dumps(
                {
                    "status": "complete",
                    "has_more": False,
                    "priority_emails": priority_emails,
                },
                indent=2,
                default=str,
            )

        except Exception as e:
            logger.error(f"Error in triage_priority_emails: {e}")
            return json.dumps({"error": str(e)})
