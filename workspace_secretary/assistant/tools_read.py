"""Read-only tools for the LangGraph assistant.

These tools only read from the database and do not modify any state.
They are safe to execute without human approval.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from workspace_secretary.assistant.context import get_context
from workspace_secretary.db.queries import emails as email_queries
from workspace_secretary.signals import analyze_signals as shared_analyze_signals
from workspace_secretary.signals import compute_priority, format_signals_display

if TYPE_CHECKING:
    from workspace_secretary.assistant.context import AssistantContext

logger = logging.getLogger(__name__)


# =============================================================================
# Email Read Tools
# =============================================================================


@tool
def list_folders() -> str:
    """List all email folders available in the mailbox.

    Returns a list of folder names that can be used with other email tools.
    """
    ctx = get_context()
    folders = email_queries.get_folders(ctx.db)
    if not folders:
        return "No folders found. The mailbox may not be synced yet."
    return f"Available folders:\n" + "\n".join(f"- {f}" for f in folders)


@tool
def search_emails(
    query: str,
    folder: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    has_attachments: Optional[bool] = None,
) -> str:
    """Search emails using full-text search with optional filters.

    Args:
        query: Search query for subject and body text. Use natural language.
        folder: Email folder to search (default: INBOX)
        limit: Maximum number of results (default: 20, max: 100)
        unread_only: Only return unread emails
        from_addr: Filter by sender email (partial match)
        to_addr: Filter by recipient email (partial match)
        has_attachments: Filter by attachment presence

    Returns:
        List of matching emails with UID, subject, sender, date, and preview.
    """
    ctx = get_context()
    limit = min(limit, 100)

    # Build filters dict
    filters: dict[str, Any] = {}
    if unread_only:
        filters["is_unread"] = True
    if from_addr:
        filters["from_addr"] = from_addr
    if to_addr:
        filters["to_addr"] = to_addr
    if has_attachments is not None:
        filters["has_attachments"] = has_attachments

    if query.strip():
        results = email_queries.search_emails_advanced(
            ctx.db, query, folder, limit, filters
        )
    else:
        results = email_queries.search_emails(
            ctx.db,
            folder=folder,
            is_unread=filters.get("is_unread"),
            from_addr=filters.get("from_addr"),
            to_addr=filters.get("to_addr"),
            limit=limit,
        )

    if not results:
        return f"No emails found matching '{query}' in {folder}."

    lines = [f"Found {len(results)} email(s) in {folder}:\n"]
    for email in results:
        date_str = _format_date(email.get("date"))
        unread_marker = "📫 " if email.get("is_unread") else "📭 "
        attachment_marker = "📎" if email.get("has_attachments") else ""
        lines.append(
            f"{unread_marker}[UID:{email['uid']}] {date_str}\n"
            f"  From: {email['from_addr']}\n"
            f"  Subject: {email['subject']} {attachment_marker}\n"
            f"  Preview: {email.get('preview', '')[:150]}...\n"
        )

    return "\n".join(lines)


@tool
def get_email_details(uid: int, folder: str = "INBOX") -> str:
    """Get full details of an email by its UID.

    Args:
        uid: The unique identifier of the email
        folder: The folder containing the email (default: INBOX)

    Returns:
        Full email content including headers, body, and analysis signals.
    """
    ctx = get_context()
    email = email_queries.get_email(ctx.db, uid, folder)

    if not email:
        return f"Email with UID {uid} not found in {folder}."

    # Build signal analysis
    signals = _analyze_email_signals(email, ctx)

    date_str = _format_date(email.get("date"))
    labels = email.get("gmail_labels") or []
    if isinstance(labels, str):
        labels = json.loads(labels)

    body = email.get("body_text") or email.get("body_html") or "(No content)"
    if len(body) > 5000:
        body = body[:5000] + "\n... (truncated)"

    attachments = email.get("attachment_filenames") or []
    if isinstance(attachments, str):
        attachments = json.loads(attachments)
    attachment_info = f"\nAttachments: {', '.join(attachments)}" if attachments else ""

    return f"""Email Details [UID:{uid}]
=====================================
From: {email["from_addr"]}
To: {email["to_addr"]}
CC: {email.get("cc_addr", "")}
Date: {date_str}
Subject: {email["subject"]}
Labels: {", ".join(labels) if labels else "None"}
Unread: {email.get("is_unread", False)}
Important: {email.get("is_important", False)}{attachment_info}

--- Signals ---
{_format_signals(signals)}

--- Body ---
{body}
"""


@tool
def get_email_thread(uid: int, folder: str = "INBOX") -> str:
    """Get all emails in a conversation thread.

    Args:
        uid: UID of any email in the thread
        folder: Folder containing the email (default: INBOX)

    Returns:
        All emails in the thread, ordered by date.
    """
    ctx = get_context()
    thread = email_queries.get_thread(ctx.db, uid, folder)

    if not thread:
        return f"No thread found for UID {uid} in {folder}."

    lines = [f"Thread with {len(thread)} message(s):\n"]
    for i, email in enumerate(thread, 1):
        date_str = _format_date(email.get("date"))
        body = email.get("body_text") or "(No text content)"
        body_preview = body[:500] + "..." if len(body) > 500 else body

        lines.append(
            f"--- Message {i} [UID:{email['uid']}] ---\n"
            f"From: {email['from_addr']}\n"
            f"To: {email['to_addr']}\n"
            f"Date: {date_str}\n"
            f"Subject: {email['subject']}\n"
            f"\n{body_preview}\n"
        )

    return "\n".join(lines)


@tool
def get_unread_messages(folder: str = "INBOX", limit: int = 20) -> str:
    """Get unread emails from a folder.

    Args:
        folder: Email folder (default: INBOX)
        limit: Maximum number of results (default: 20)

    Returns:
        List of unread emails with details.
    """
    ctx = get_context()
    results = email_queries.get_inbox_emails(ctx.db, folder, limit, 0, unread_only=True)

    if not results:
        return f"No unread emails in {folder}."

    lines = [f"📬 {len(results)} unread email(s) in {folder}:\n"]
    for email in results:
        date_str = _format_date(email.get("date"))
        attachment_marker = " 📎" if email.get("has_attachments") else ""
        lines.append(
            f"[UID:{email['uid']}] {date_str}\n"
            f"  From: {email['from_addr']}\n"
            f"  Subject: {email['subject']}{attachment_marker}\n"
        )

    return "\n".join(lines)


@tool
def get_daily_briefing(date: Optional[str] = None) -> str:
    """Get a daily briefing with priority emails and calendar events.

    Args:
        date: Date for briefing in YYYY-MM-DD format (default: today)

    Returns:
        Summary of priority emails and scheduled events.
    """
    ctx = get_context()
    tz = ZoneInfo(ctx.timezone)

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError:
            return f"Invalid date format: {date}. Use YYYY-MM-DD."
    else:
        target_date = datetime.now(tz)

    # Get unread emails
    unread = email_queries.get_inbox_emails(ctx.db, "INBOX", 50, 0, unread_only=True)

    # Categorize emails
    priority_emails = []
    vip_emails = []

    for email in unread:
        from_addr = (email.get("from_addr") or "").lower()
        is_vip = any(vip.lower() in from_addr for vip in ctx.vip_senders)

        if is_vip:
            vip_emails.append(email)
        else:
            # Check if directly addressed
            to_addr = (email.get("to_addr") or "").lower()
            if ctx.user_email.lower() in to_addr:
                priority_emails.append(email)

    # Build briefing
    date_str = target_date.strftime("%A, %B %d, %Y")
    lines = [f"📅 Daily Briefing for {date_str}\n", "=" * 50, ""]

    # VIP section
    if vip_emails:
        lines.append(f"⭐ VIP Messages ({len(vip_emails)}):")
        for email in vip_emails[:5]:
            lines.append(f"  • {email['from_addr']}: {email['subject'][:60]}")
        lines.append("")

    # Priority section
    if priority_emails:
        lines.append(f"🔴 Priority (Directly Addressed) ({len(priority_emails)}):")
        for email in priority_emails[:10]:
            lines.append(f"  • {email['from_addr']}: {email['subject'][:60]}")
        lines.append("")

    # Summary stats
    total_unread = len(unread)
    lines.append(f"📊 Summary:")
    lines.append(f"  • Total unread: {total_unread}")
    lines.append(f"  • VIP messages: {len(vip_emails)}")
    lines.append(f"  • Priority: {len(priority_emails)}")
    lines.append(f"  • Other: {total_unread - len(vip_emails) - len(priority_emails)}")

    # Calendar events (via engine client)
    try:
        start = target_date.replace(hour=0, minute=0, second=0).isoformat()
        end = target_date.replace(hour=23, minute=59, second=59).isoformat()
        events = ctx.engine.list_calendar_events(start, end)

        if events.get("events"):
            lines.append("")
            lines.append(f"📆 Today's Calendar ({len(events['events'])} events):")
            for event in events["events"][:10]:
                time_str = event.get("start", {}).get("dateTime", "All day")
                if "T" in time_str:
                    time_str = time_str.split("T")[1][:5]
                lines.append(f"  • {time_str} - {event.get('summary', 'No title')}")
    except Exception as e:
        logger.warning(f"Could not fetch calendar: {e}")
        lines.append("\n📆 Calendar: Unable to fetch (engine may be offline)")

    return "\n".join(lines)


# =============================================================================
# Calendar Read Tools
# =============================================================================


@tool
def list_calendar_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    calendar_id: str = "primary",
) -> str:
    """List calendar events within a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format (default: today)
        end_date: End date in YYYY-MM-DD format (default: 7 days from start)
        calendar_id: Calendar ID (default: primary)

    Returns:
        List of calendar events with time, title, and details.
    """
    ctx = get_context()
    tz = ZoneInfo(ctx.timezone)

    # Parse dates
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError:
            return f"Invalid start_date format: {start_date}. Use YYYY-MM-DD."
    else:
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=tz
            )
        except ValueError:
            return f"Invalid end_date format: {end_date}. Use YYYY-MM-DD."
    else:
        end = start + timedelta(days=7)

    try:
        result = ctx.engine.list_calendar_events(
            start.isoformat(), end.isoformat(), calendar_id
        )
    except Exception as e:
        return f"Error fetching calendar events: {e}"

    events = result.get("events", [])
    if not events:
        return f"No events found between {start.date()} and {end.date()}."

    lines = [f"📆 Calendar Events ({start.date()} to {end.date()}):\n"]

    current_date = None
    for event in events:
        # Parse event start time
        event_start = event.get("start", {})
        if "dateTime" in event_start:
            event_dt = datetime.fromisoformat(
                event_start["dateTime"].replace("Z", "+00:00")
            )
            event_date = event_dt.date()
            time_str = event_dt.strftime("%H:%M")
        else:
            event_date = datetime.strptime(
                event_start.get("date", ""), "%Y-%m-%d"
            ).date()
            time_str = "All day"

        # Group by date
        if event_date != current_date:
            current_date = event_date
            lines.append(f"\n{current_date.strftime('%A, %B %d')}:")

        summary = event.get("summary", "No title")
        location = event.get("location", "")
        location_str = f" @ {location}" if location else ""
        event_id = event.get("id", "")
        id_str = f" [ID: {event_id}]" if event_id else ""

        lines.append(f"  • {time_str} - {summary}{location_str}{id_str}")

    return "\n".join(lines)


@tool
def get_calendar_availability(
    start_date: str,
    end_date: str,
    calendar_ids: Optional[list[str]] = None,
) -> str:
    """Check free/busy availability across calendars.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        calendar_ids: List of calendar IDs (default: primary only)

    Returns:
        Free/busy time slots for the specified range.
    """
    ctx = get_context()
    tz = ZoneInfo(ctx.timezone)

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=tz
        )
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD."

    calendar_ids = calendar_ids or ["primary"]

    try:
        result = ctx.engine.get_calendar_availability(
            start.isoformat(), end.isoformat(), calendar_ids
        )
    except Exception as e:
        return f"Error checking availability: {e}"

    lines = [f"📊 Availability ({start.date()} to {end.date()}):\n"]

    busy_times = result.get("calendars", {}).get("primary", {}).get("busy", [])
    if not busy_times:
        lines.append("✅ You appear to be free during this time range.")
    else:
        lines.append("Busy times:")
        for slot in busy_times:
            slot_start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
            slot_end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
            lines.append(
                f"  • {slot_start.strftime('%m/%d %H:%M')} - {slot_end.strftime('%H:%M')}"
            )

    return "\n".join(lines)


# =============================================================================
# Safe Staging Tools (create drafts, no mutations)
# =============================================================================


@tool
def create_draft_reply(
    uid: int,
    body: str,
    folder: str = "INBOX",
    reply_all: bool = False,
) -> str:
    """Create a draft reply to an email (does NOT send).

    This creates a draft in the Drafts folder. You must explicitly
    confirm sending with send_email tool.

    Args:
        uid: UID of the email to reply to
        body: Reply message body
        folder: Folder containing the original email (default: INBOX)
        reply_all: Include CC recipients (default: False)

    Returns:
        Confirmation that draft was created.
    """
    ctx = get_context()

    # Get original email for context
    original = email_queries.get_email(ctx.db, uid, folder)
    if not original:
        return f"Cannot create draft: Email UID {uid} not found in {folder}."

    try:
        result = ctx.engine.create_draft_reply(uid, folder, body, reply_all)
        return f"""✅ Draft reply created!

Original email from: {original["from_addr"]}
Subject: Re: {original["subject"]}

Draft body:
{body}

To send this draft, use the send_email tool or review in Gmail Drafts folder."""
    except Exception as e:
        return f"Error creating draft: {e}"


# =============================================================================
# Batch Operation Tools (Read-Only - Identify Candidates)
# =============================================================================


@tool
def quick_clean_inbox(
    folder: str = "INBOX",
    limit: int = 50,
    continuation_state: Optional[str] = None,
) -> str:
    """Identify cleanup candidates where user is NOT in To:/CC: and name NOT in body.

    Time-boxed to ~5 seconds. Returns partial results with continuation state
    if more emails need processing.

    Args:
        folder: Folder to clean (default: INBOX)
        limit: Max emails to process per call (default: 50)
        continuation_state: State from previous call to continue processing

    Returns:
        JSON with candidates, confidence scores, and continuation state.
    """
    import time

    ctx = get_context()
    start_time = time.time()
    timeout = 5.0  # 5 second time limit

    # Parse continuation state
    offset = 0
    if continuation_state:
        try:
            state = json.loads(continuation_state)
            offset = state.get("offset", 0)
        except json.JSONDecodeError:
            pass

    # Get emails from folder
    emails = email_queries.get_inbox_emails(
        ctx.db, folder, limit, offset, unread_only=False
    )

    candidates = []
    processed_count = 0

    for email in emails:
        # Check timeout
        if time.time() - start_time > timeout:
            break

        processed_count += 1

        # Extract fields
        to_addr = (email.get("to_addr") or "").lower()
        cc_addr = (email.get("cc_addr") or "").lower()
        body = (email.get("preview") or "").lower()
        from_addr = email.get("from_addr") or ""
        subject = email.get("subject") or ""

        # Check if user is in To: or CC:
        user_email_lower = ctx.user_email.lower()
        if user_email_lower in to_addr or user_email_lower in cc_addr:
            continue

        # Check if user's name is mentioned in body
        if ctx.identity.full_name and ctx.identity.matches_name_part(body):
            continue

        # Calculate confidence
        confidence = "medium"
        noreply_patterns = [
            "noreply",
            "no-reply",
            "donotreply",
            "automated",
            "notification",
        ]
        newsletter_patterns = ["newsletter", "digest", "update", "unsubscribe"]

        if any(pattern in from_addr.lower() for pattern in noreply_patterns):
            confidence = "high"
        elif any(
            pattern in subject.lower() or pattern in body
            for pattern in newsletter_patterns
        ):
            confidence = "high"
        elif len(to_addr.split(",")) > 10:
            confidence = "medium"
        else:
            confidence = "low"

        # Add candidate
        candidates.append(
            {
                "uid": email["uid"],
                "from_addr": from_addr,
                "to_addr": email.get("to_addr", ""),
                "cc_addr": email.get("cc_addr", ""),
                "subject": subject,
                "date": _format_date(email.get("date")),
                "preview": (email.get("preview") or "")[:300],
                "confidence": confidence,
            }
        )

    # Determine if we have more to process
    has_more = processed_count >= limit and time.time() - start_time < timeout
    status = "partial" if has_more else "complete"

    # Build continuation state
    new_continuation_state = None
    if has_more:
        new_continuation_state = json.dumps({"offset": offset + processed_count})

    result = {
        "status": status,
        "candidates": candidates,
        "has_more": has_more,
        "continuation_state": new_continuation_state,
        "processed_count": processed_count,
        "time_limit_reached": time.time() - start_time > timeout,
    }

    return json.dumps(result, indent=2)


@tool
def triage_priority_emails(
    folder: str = "INBOX",
    limit: int = 50,
    continuation_state: Optional[str] = None,
) -> str:
    """Identify high-priority emails: user in To: with <5 recipients OR <15 recipients AND name in body.

    Time-boxed to ~5 seconds. Returns partial results with continuation state.

    Args:
        folder: Folder to triage (default: INBOX)
        limit: Max emails to process per call (default: 50)
        continuation_state: State from previous call to continue processing

    Returns:
        JSON with priority emails, signals, and continuation state.
    """
    import time

    ctx = get_context()
    start_time = time.time()
    timeout = 5.0

    # Parse continuation state
    offset = 0
    if continuation_state:
        try:
            state = json.loads(continuation_state)
            offset = state.get("offset", 0)
        except json.JSONDecodeError:
            pass

    # Get unread emails
    emails = email_queries.get_inbox_emails(
        ctx.db, folder, limit, offset, unread_only=True
    )

    priority_emails = []
    processed_count = 0

    for email in emails:
        # Check timeout
        if time.time() - start_time > timeout:
            break

        processed_count += 1

        # Get full email for signals
        full_email = email_queries.get_email(ctx.db, email["uid"], folder)
        if not full_email:
            continue

        # Analyze signals
        signals = _analyze_email_signals(full_email, ctx)

        # Check if addressed to user
        to_addr = (full_email.get("to_addr") or "").lower()
        user_email_lower = ctx.user_email.lower()

        if user_email_lower not in to_addr:
            continue

        # Count recipients
        recipient_count = len([r.strip() for r in to_addr.split(",") if r.strip()])

        # Priority logic
        is_priority = False
        if recipient_count < 5:
            is_priority = True
        elif recipient_count < 15 and signals["mentions_my_name"]:
            is_priority = True

        if not is_priority:
            continue

        # Add to priority list
        priority_emails.append(
            {
                "uid": full_email["uid"],
                "from_addr": full_email.get("from_addr", ""),
                "to_addr": full_email.get("to_addr", ""),
                "cc_addr": full_email.get("cc_addr", ""),
                "subject": full_email.get("subject", ""),
                "date": _format_date(full_email.get("date")),
                "preview": (full_email.get("body_text") or "")[:300],
                "signals": {
                    "is_from_vip": signals["is_from_vip"],
                    "is_addressed_to_me": signals["is_addressed_to_me"],
                    "mentions_my_name": signals["mentions_my_name"],
                    "has_question": signals["has_question"],
                    "mentions_deadline": signals["mentions_deadline"],
                    "mentions_meeting": signals["mentions_meeting"],
                    "has_attachments": signals["has_attachments"],
                },
            }
        )

    # Determine if we have more to process
    has_more = processed_count >= limit and time.time() - start_time < timeout
    status = "partial" if has_more else "complete"

    new_continuation_state = None
    if has_more:
        new_continuation_state = json.dumps({"offset": offset + processed_count})

    result = {
        "status": status,
        "priority_emails": priority_emails,
        "has_more": has_more,
        "continuation_state": new_continuation_state,
        "processed_count": processed_count,
    }

    return json.dumps(result, indent=2)


@tool
def triage_remaining_emails(
    folder: str = "INBOX",
    limit: int = 50,
    continuation_state: Optional[str] = None,
) -> str:
    """Process remaining emails not caught by priority triage with signals for human decision.

    Time-boxed to ~5 seconds. Returns partial results with continuation state.

    Args:
        folder: Folder to triage (default: INBOX)
        limit: Max emails to process per call (default: 50)
        continuation_state: State from previous call to continue processing

    Returns:
        JSON with remaining emails, signals, and continuation state.
    """
    import time

    ctx = get_context()
    start_time = time.time()
    timeout = 5.0

    # Parse continuation state
    offset = 0
    if continuation_state:
        try:
            state = json.loads(continuation_state)
            offset = state.get("offset", 0)
        except json.JSONDecodeError:
            pass

    # Get unread emails
    emails = email_queries.get_inbox_emails(
        ctx.db, folder, limit, offset, unread_only=True
    )

    remaining_emails = []
    processed_count = 0

    for email in emails:
        # Check timeout
        if time.time() - start_time > timeout:
            break

        processed_count += 1

        # Get full email for signals
        full_email = email_queries.get_email(ctx.db, email["uid"], folder)
        if not full_email:
            continue

        # Analyze signals
        signals = _analyze_email_signals(full_email, ctx)

        # Add to remaining list
        remaining_emails.append(
            {
                "uid": full_email["uid"],
                "from_addr": full_email.get("from_addr", ""),
                "to_addr": full_email.get("to_addr", ""),
                "cc_addr": full_email.get("cc_addr", ""),
                "subject": full_email.get("subject", ""),
                "date": _format_date(full_email.get("date")),
                "preview": (full_email.get("body_text") or "")[:300],
                "signals": {
                    "is_from_vip": signals["is_from_vip"],
                    "is_addressed_to_me": signals["is_addressed_to_me"],
                    "mentions_my_name": signals["mentions_my_name"],
                    "has_question": signals["has_question"],
                    "mentions_deadline": signals["mentions_deadline"],
                    "mentions_meeting": signals["mentions_meeting"],
                    "has_attachments": signals["has_attachments"],
                },
            }
        )

    # Determine if we have more to process
    has_more = processed_count >= limit and time.time() - start_time < timeout
    status = "partial" if has_more else "complete"

    new_continuation_state = None
    if has_more:
        new_continuation_state = json.dumps({"offset": offset + processed_count})

    result = {
        "status": status,
        "remaining_emails": remaining_emails,
        "has_more": has_more,
        "continuation_state": new_continuation_state,
        "processed_count": processed_count,
    }

    return json.dumps(result, indent=2)


# =============================================================================
# Helper Functions
# =============================================================================


def _format_date(date_val: Any) -> str:
    """Format a date value for display."""
    if not date_val:
        return "Unknown date"
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except ValueError:
            return date_val
    if isinstance(date_val, datetime):
        return date_val.strftime("%Y-%m-%d %H:%M")
    return str(date_val)


def _analyze_email_signals(
    email: dict[str, Any], ctx: "AssistantContext"
) -> dict[str, Any]:
    """Analyze email for actionable signals using shared signal module.

    This is a thin wrapper that calls the shared analyze_signals function
    with the context's user info and VIP list.
    """
    return shared_analyze_signals(
        email=email,
        user_email=ctx.user_email,
        identity=ctx.identity,
        vip_senders=ctx.vip_senders,
    )


def _format_signals(signals: dict[str, Any]) -> str:
    """Format signals for display."""
    lines = []
    if signals["is_from_vip"]:
        lines.append("⭐ From VIP sender")
    if signals["is_addressed_to_me"]:
        lines.append("📍 Directly addressed to you")
    if signals["mentions_my_name"]:
        lines.append("👤 Your name mentioned")
    if signals["has_question"]:
        lines.append("❓ Contains question")
    if signals["mentions_deadline"]:
        lines.append("⏰ Mentions deadline/urgency")
    if signals["mentions_meeting"]:
        lines.append("📅 Mentions meeting/scheduling")
    if signals["has_attachments"]:
        lines.append("📎 Has attachments")
    if signals["is_important"]:
        lines.append("🔴 Marked important")

    return "\n".join(lines) if lines else "No significant signals detected."


# =============================================================================
# Export list
# =============================================================================


@tool
def check_emails_needing_response(
    folder: str = "INBOX",
    limit: int = 20,
) -> str:
    """Check for unread emails that may need a response.

    Identifies emails where:
    - Email is unread
    - User is directly in To: field
    - Email contains a question

    Per AGENTS.md auto-draft rules, these are candidates for draft creation.
    Returns structured JSON with email details for the LLM to act on.

    Args:
        folder: Email folder to search (default: INBOX)
        limit: Maximum emails to check (default: 20)

    Returns:
        JSON with emails needing response and their signals
    """
    ctx = get_context()

    try:
        # Use query functions directly with db connection (same pattern as search_emails tool)
        emails = email_queries.search_emails(
            ctx.db,
            folder=folder,
            is_unread=True,
            limit=limit,
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "error": str(e),
                "emails_needing_response": [],
            }
        )

    emails_needing_response = []

    for email in emails:
        signals = _analyze_email_signals(email, ctx)

        # Per AGENTS.md: auto-draft when has_question AND user in To:
        if signals["is_addressed_to_me"] and signals["has_question"]:
            # Calculate priority for sorting
            priority, priority_reason = compute_priority(signals)

            emails_needing_response.append(
                {
                    "uid": email.get("uid"),
                    "folder": folder,
                    "from_addr": email.get("from_addr"),
                    "to_addr": email.get("to_addr"),
                    "subject": email.get("subject"),
                    "date": _format_date(email.get("date")),
                    "preview": (email.get("body_text") or "")[:300],
                    "priority": priority,
                    "priority_reason": priority_reason,
                    "signals": {
                        "is_from_vip": signals["is_from_vip"],
                        "mentions_deadline": signals["mentions_deadline"],
                        "mentions_meeting": signals["mentions_meeting"],
                        "has_attachments": signals["has_attachments"],
                    },
                }
            )

    # Sort by priority (high first)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    emails_needing_response.sort(key=lambda e: priority_order.get(e["priority"], 2))

    return json.dumps(
        {
            "status": "complete",
            "emails_checked": len(emails),
            "emails_needing_response": emails_needing_response,
            "count": len(emails_needing_response),
            "instruction": (
                "Per AGENTS.md: Use create_draft_reply to auto-draft responses. "
                "Show user each draft for approval before sending."
            )
            if emails_needing_response
            else "No emails currently need a response.",
        },
        indent=2,
    )


READ_ONLY_TOOLS = [
    list_folders,
    search_emails,
    get_email_details,
    get_email_thread,
    get_unread_messages,
    get_daily_briefing,
    list_calendar_events,
    get_calendar_availability,
    create_draft_reply,
    quick_clean_inbox,
    triage_priority_emails,
    triage_remaining_emails,
    check_emails_needing_response,
]
