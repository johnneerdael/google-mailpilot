"""Mutation tools for the LangGraph assistant.

These tools modify state (emails, calendar) and REQUIRE human approval
before execution per AGENTS.md rules.
"""

import logging
from typing import Optional

from langchain_core.tools import tool

from workspace_secretary.assistant.context import get_context
from workspace_secretary.db.queries import emails as email_queries

logger = logging.getLogger(__name__)


# =============================================================================
# Email Mutation Tools
# =============================================================================


@tool
def mark_as_read(uid: int, folder: str = "INBOX") -> str:
    """Mark an email as read.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        uid: UID of the email to mark as read
        folder: Folder containing the email (default: INBOX)

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    # Verify email exists
    email = email_queries.get_email(ctx.db, uid, folder)
    if not email:
        return f"Email UID {uid} not found in {folder}."

    try:
        ctx.engine.mark_read(uid, folder)
        # Update local cache
        email_queries.mark_email_read(ctx.db, uid, folder, is_read=True)
        return f"✅ Marked email as read: [{uid}] {email['subject'][:50]}"
    except Exception as e:
        return f"Error marking email as read: {e}"


@tool
def mark_as_unread(uid: int, folder: str = "INBOX") -> str:
    """Mark an email as unread.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        uid: UID of the email to mark as unread
        folder: Folder containing the email (default: INBOX)

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    email = email_queries.get_email(ctx.db, uid, folder)
    if not email:
        return f"Email UID {uid} not found in {folder}."

    try:
        ctx.engine.mark_unread(uid, folder)
        email_queries.mark_email_read(ctx.db, uid, folder, is_read=False)
        return f"✅ Marked email as unread: [{uid}] {email['subject'][:50]}"
    except Exception as e:
        return f"Error marking email as unread: {e}"


@tool
def move_email(uid: int, destination: str, folder: str = "INBOX") -> str:
    """Move an email to a different folder.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        uid: UID of the email to move
        destination: Destination folder name (e.g., "Archive", "[Gmail]/Trash")
        folder: Current folder (default: INBOX)

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    email = email_queries.get_email(ctx.db, uid, folder)
    if not email:
        return f"Email UID {uid} not found in {folder}."

    try:
        ctx.engine.move_email(uid, folder, destination)
        # Delete from local cache (will be re-synced in new folder)
        email_queries.delete_email(ctx.db, uid, folder)
        return f"✅ Moved email to {destination}: [{uid}] {email['subject'][:50]}"
    except Exception as e:
        return f"Error moving email: {e}"


@tool
def modify_gmail_labels(
    uid: int,
    labels: list[str],
    action: str,
    folder: str = "INBOX",
) -> str:
    """Add or remove Gmail labels from an email.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        uid: UID of the email
        labels: List of label names to add/remove
        action: "add" or "remove"
        folder: Folder containing the email (default: INBOX)

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    if action not in ("add", "remove"):
        return f"Invalid action: {action}. Must be 'add' or 'remove'."

    email = email_queries.get_email(ctx.db, uid, folder)
    if not email:
        return f"Email UID {uid} not found in {folder}."

    try:
        ctx.engine.modify_labels(uid, folder, labels, action)
        label_str = ", ".join(labels)
        action_past = "Added" if action == "add" else "Removed"
        return (
            f"✅ {action_past} labels [{label_str}] on email: {email['subject'][:50]}"
        )
    except Exception as e:
        return f"Error modifying labels: {e}"


@tool
def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
) -> str:
    """Send a new email.

    ⚠️ MUTATION: Requires user confirmation before execution.
    NEVER call this without showing the user the draft first!

    Args:
        to: List of recipient email addresses
        subject: Email subject line
        body: Email body text
        cc: Optional list of CC recipients

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    if not to:
        return "Error: At least one recipient is required."

    try:
        result = ctx.engine.send_email(to, subject, body, cc)
        recipients = ", ".join(to)
        return f"✅ Email sent successfully!\n\nTo: {recipients}\nSubject: {subject}"
    except Exception as e:
        return f"Error sending email: {e}"


# =============================================================================
# Calendar Mutation Tools
# =============================================================================


@tool
def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    calendar_id: str = "primary",
    meeting_type: Optional[str] = None,
) -> str:
    """Create a new calendar event.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        summary: Event title
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS)
        end_time: End time in ISO format
        description: Optional event description
        location: Optional location
        calendar_id: Calendar ID (default: primary)
        meeting_type: Optional meeting type (e.g., "video" for Google Meet)

    Returns:
        Confirmation with event details.
    """
    ctx = get_context()

    try:
        result = ctx.engine.create_calendar_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            calendar_id=calendar_id,
            meeting_type=meeting_type,
        )

        # API returns event_id at top level for queued events, or in event.id for direct creates
        event_id = result.get("event_id") or result.get("event", {}).get(
            "id", "unknown"
        )
        pending = result.get("pending", False)
        status_note = " (pending sync)" if pending else ""
        return f"""✅ Calendar event created{status_note}!

Title: {summary}
Start: {start_time}
End: {end_time}
Location: {location or "Not specified"}
Event ID: {event_id}"""
    except Exception as e:
        return f"Error creating calendar event: {e}"


@tool
def respond_to_meeting(
    event_id: str,
    response: str,
    calendar_id: str = "primary",
) -> str:
    """Respond to a meeting invitation.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        event_id: The calendar event ID
        response: Response type - "accepted", "declined", or "tentative"
        calendar_id: Calendar ID (default: primary)

    Returns:
        Confirmation message.
    """
    ctx = get_context()

    valid_responses = ("accepted", "declined", "tentative")
    if response not in valid_responses:
        return f"Invalid response: {response}. Must be one of: {', '.join(valid_responses)}"

    # Check if this is a local/queued event (not yet synced to Google Calendar)
    if event_id.startswith("local:"):
        return (
            f"❌ Cannot respond to event '{event_id}': This event is still pending sync "
            f"to Google Calendar. Wait for the event to sync (check list_calendar_events "
            f"for events without 'local:' prefix), or the event may have been created "
            f"locally and not yet confirmed by Google Calendar."
        )

    try:
        result = ctx.engine.respond_to_meeting(event_id, calendar_id, response)
        # API returns {"status": "ok", "event": {...}} on success
        if result.get("status") == "ok" or result.get("event"):
            return f"✅ Meeting response recorded: {response}"
        return (
            f"❌ Failed to respond to meeting: {result.get('detail', 'Unknown error')}"
        )
    except Exception as e:
        return f"❌ Error responding to meeting: {e}"


# =============================================================================
# Batch Mutation Tools
# =============================================================================


@tool
def execute_clean_batch(uids: list[int], folder: str = "INBOX") -> str:
    """Execute approved batch cleanup - move emails to Secretary/Auto-Cleaned.

    ⚠️ MUTATION: Only call after user has approved the cleanup candidates.

    Args:
        uids: List of email UIDs to clean (must be pre-approved by user)
        folder: Source folder (default: INBOX)

    Returns:
        Summary of cleaned emails.
    """
    ctx = get_context()

    if not uids:
        return "No UIDs provided for cleanup."

    destination = "Secretary/Auto-Cleaned"
    success_count = 0
    errors = []

    for uid in uids:
        try:
            ctx.engine.move_email(uid, folder, destination)
            email_queries.delete_email(ctx.db, uid, folder)
            success_count += 1
        except Exception as e:
            errors.append(f"UID {uid}: {e}")

    result = f"✅ Cleaned {success_count}/{len(uids)} emails → {destination}"
    if errors:
        result += f"\n\n⚠️ Errors ({len(errors)}):\n" + "\n".join(errors[:5])

    return result


@tool
def process_email(
    uid: int,
    folder: str,
    actions: dict,
) -> str:
    """Execute combined actions on an email atomically.

    ⚠️ MUTATION: Requires user confirmation before execution.

    Args:
        uid: UID of the email to process
        folder: Folder containing the email
        actions: Dict with:
            - mark_read: bool (optional)
            - labels_add: list[str] (optional)
            - labels_remove: list[str] (optional)
            - move_to: str (optional, folder name)

    Returns:
        Confirmation message with all actions performed.
    """
    ctx = get_context()

    # Verify email exists
    email = email_queries.get_email(ctx.db, uid, folder)
    if not email:
        return f"Email UID {uid} not found in {folder}."

    performed_actions = []
    errors = []

    try:
        # Mark as read
        if actions.get("mark_read") is not None:
            try:
                if actions["mark_read"]:
                    ctx.engine.mark_read(uid, folder)
                    email_queries.mark_email_read(ctx.db, uid, folder, is_read=True)
                    performed_actions.append("✅ Marked as read")
                else:
                    ctx.engine.mark_unread(uid, folder)
                    email_queries.mark_email_read(ctx.db, uid, folder, is_read=False)
                    performed_actions.append("✅ Marked as unread")
            except Exception as e:
                errors.append(f"Mark read/unread failed: {e}")

        # Add labels
        if actions.get("labels_add"):
            try:
                ctx.engine.modify_labels(uid, folder, actions["labels_add"], "add")
                label_str = ", ".join(actions["labels_add"])
                performed_actions.append(f"✅ Added labels: {label_str}")
            except Exception as e:
                errors.append(f"Add labels failed: {e}")

        # Remove labels
        if actions.get("labels_remove"):
            try:
                ctx.engine.modify_labels(
                    uid, folder, actions["labels_remove"], "remove"
                )
                label_str = ", ".join(actions["labels_remove"])
                performed_actions.append(f"✅ Removed labels: {label_str}")
            except Exception as e:
                errors.append(f"Remove labels failed: {e}")

        # Move email (must be last, as it changes the folder)
        if actions.get("move_to"):
            try:
                destination = actions["move_to"]
                ctx.engine.move_email(uid, folder, destination)
                email_queries.delete_email(ctx.db, uid, folder)
                performed_actions.append(f"✅ Moved to: {destination}")
            except Exception as e:
                errors.append(f"Move failed: {e}")

        # Build result message
        result_lines = [f"Email processed [UID:{uid}] {email['subject'][:50]}"]
        result_lines.append("\nActions performed:")
        result_lines.extend(performed_actions)

        if errors:
            result_lines.append("\n⚠️ Errors encountered:")
            result_lines.extend(errors)

        return "\n".join(result_lines)

    except Exception as e:
        return f"Error processing email: {e}"


# =============================================================================
# Export list
# =============================================================================

MUTATION_TOOLS = [
    mark_as_read,
    mark_as_unread,
    move_email,
    modify_gmail_labels,
    send_email,
    create_calendar_event,
    respond_to_meeting,
    execute_clean_batch,
    process_email,
]
