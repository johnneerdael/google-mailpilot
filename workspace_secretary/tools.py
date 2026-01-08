"""MCP tools implementation for email operations."""

import json
import logging
from datetime import datetime
from typing import List, Optional, Union, Dict, Any

from mcp.server.fastmcp import FastMCP, Context

from workspace_secretary.imap_client import ImapClient
from workspace_secretary.calendar_client import CalendarClient
from workspace_secretary.gmail_client import GmailClient
from workspace_secretary.resources import (
    get_client_from_context,
    get_smtp_client_from_context,
    get_calendar_client_from_context,
    get_gmail_client_from_context,
)
from workspace_secretary.models import EmailAddress

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP, imap_client: ImapClient) -> None:
    """Register MCP tools.

    Args:
        mcp: MCP server
        imap_client: IMAP client
    """

    # List folders tool
    @mcp.tool()
    async def list_folders(ctx: Context) -> str:
        """List available email folders.

        Args:
            ctx: MCP context

        Returns:
            JSON string with folder list
        """
        client = get_client_from_context(ctx)
        folders = client.list_folders()
        return json.dumps(folders, indent=2)

    # Search emails tool
    @mcp.tool()
    async def search_emails(
        criteria: Union[str, List[Any], Dict[str, Any]],
        folder: str = "INBOX",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Search for emails.

        Args:
            criteria: Search criteria (e.g., "ALL", "UNSEEN", or complex criteria)
            folder: Folder to search in
            ctx: MCP context

        Returns:
            JSON string with search results
        """
        client = get_client_from_context(ctx)

        try:
            # imap_client.search handles dictionary criteria natively and maps
            # them to proper IMAP search lists with AND logic.
            uids = client.search(criteria, folder=folder)

            if not uids:
                return json.dumps([], indent=2)

            # Fetch basic info for search results
            emails = client.fetch_emails(uids, folder=folder, limit=50)

            results = []
            for uid, email_obj in emails.items():
                results.append(
                    {
                        "uid": uid,
                        "from": str(email_obj.from_),
                        "subject": email_obj.subject,
                        "date": email_obj.date.isoformat() if email_obj.date else None,
                        "flags": email_obj.flags,
                    }
                )

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    # Get email details tool
    @mcp.tool()
    async def get_email_details(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Get full details of a specific email.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            JSON string with email details
        """
        client = get_client_from_context(ctx)

        try:
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return json.dumps({"error": "Email not found"}, indent=2)

            # Format for JSON
            details = {
                "uid": uid,
                "folder": folder,
                "message_id": email_obj.message_id,
                "from": str(email_obj.from_),
                "to": [str(t) for t in email_obj.to],
                "cc": [str(c) for c in email_obj.cc],
                "subject": email_obj.subject,
                "date": email_obj.date.isoformat() if email_obj.date else None,
                "content": email_obj.content.get_best_content(),
                "flags": email_obj.flags,
                "attachments": [
                    {
                        "filename": a.filename,
                        "content_type": a.content_type,
                        "size": a.size,
                    }
                    for a in email_obj.attachments
                ],
                "gmail_thread_id": email_obj.gmail_thread_id,
                "gmail_labels": email_obj.gmail_labels,
            }

            return json.dumps(details, indent=2)
        except Exception as e:
            logger.error(f"Error getting email details: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    # Create a draft reply tool
    @mcp.tool()
    async def create_draft_reply(
        folder: str,
        uid: int,
        reply_body: str,
        reply_all: bool = False,
        cc: Optional[List[str]] = None,
        body_html: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> Dict[str, Any]:
        """Create a draft reply to an email.

        Args:
            folder: Folder containing the email
            uid: Email UID
            reply_body: Content of the reply
            reply_all: Whether to reply to all
            cc: Additional CC addresses
            body_html: Optional HTML content
            ctx: MCP context

        Returns:
            Processing result
        """
        from workspace_secretary.smtp_client import create_reply_mime

        client = get_client_from_context(ctx)

        try:
            # Fetch original email
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return {"status": "error", "message": f"Email with UID {uid} not found"}

            # Determine sender (reply_from)
            reply_from = EmailAddress(name="Me", address=client.config.username)

            # Create MIME message
            mime_message = create_reply_mime(
                original_email=email_obj,
                reply_to=reply_from,
                body=reply_body,
                subject=None,  # Will be auto-generated with Re:
                reply_all=reply_all,
                html_body=body_html,
                cc=[EmailAddress.parse(c) for c in cc] if cc else None,
            )

            # Save draft
            draft_uid = client.save_draft_mime(mime_message)

            if draft_uid:
                drafts_folder = client._get_drafts_folder()
                return {
                    "status": "success",
                    "message": "Draft created successfully",
                    "draft_uid": str(draft_uid),
                    "draft_folder": drafts_folder,
                }
            else:
                return {"status": "error", "message": "Failed to save draft"}

        except Exception as e:
            logger.error(f"Error creating draft: {e}")
            return {"status": "error", "message": str(e)}

    # Move email to a different folder
    @mcp.tool()
    async def move_email(
        folder: str,
        uid: int,
        target_folder: str,
        ctx: Context,
    ) -> str:
        """Move email to another folder.

        Args:
            folder: Source folder
            uid: Email UID
            target_folder: Target folder
            ctx: MCP context

        Returns:
            Success message or error message
        """
        client = get_client_from_context(ctx)

        try:
            success = client.move_email(uid, folder, target_folder)
            if success:
                return f"Email moved from {folder} to {target_folder}"
            else:
                return "Failed to move email"
        except Exception as e:
            logger.error(f"Error moving email: {e}")
            return f"Error: {e}"

    # Mark email as read
    @mcp.tool()
    async def mark_as_read(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Mark email as read.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Success message
        """
        client = get_client_from_context(ctx)
        try:
            client.mark_email(uid, folder, r"\Seen", True)
            return "Email marked as read"
        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
            return f"Error: {e}"

    # Mark email as unread
    @mcp.tool()
    async def mark_as_unread(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Mark email as unread.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Success message
        """
        client = get_client_from_context(ctx)
        try:
            client.mark_email(uid, folder, r"\Seen", False)
            return "Email marked as unread"
        except Exception as e:
            logger.error(f"Error marking email as unread: {e}")
            return f"Error: {e}"

    # Get email thread tool
    @mcp.tool()
    async def get_email_thread(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Get all emails in a conversation thread.

        Args:
            folder: Folder name
            uid: UID of an email in the thread
            ctx: MCP context

        Returns:
            JSON string with emails in the thread
        """
        client = get_client_from_context(ctx)

        try:
            emails = client.fetch_thread(uid, folder)

            results = []
            for email_obj in emails:
                results.append(
                    {
                        "uid": email_obj.uid,
                        "from": str(email_obj.from_),
                        "to": [str(t) for t in email_obj.to],
                        "subject": email_obj.subject,
                        "date": email_obj.date.isoformat() if email_obj.date else None,
                        "snippet": email_obj.get_snippet(150),
                        "flags": email_obj.flags,
                    }
                )

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error getting email thread: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    # Modify Gmail labels tool
    @mcp.tool()
    async def modify_gmail_labels(
        folder: str,
        uid: int,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Add or remove Gmail labels from an email.

        Args:
            folder: Folder name
            uid: Email UID
            add_labels: List of labels to add
            remove_labels: List of labels to remove
            ctx: MCP context

        Returns:
            Success or error message
        """
        client = get_client_from_context(ctx)

        try:
            results = []
            if add_labels:
                success = client.add_gmail_labels(uid, folder, add_labels)
                if success:
                    results.append(f"Added labels: {', '.join(add_labels)}")
                else:
                    results.append(f"Failed to add labels: {', '.join(add_labels)}")

            if remove_labels:
                success = client.remove_gmail_labels(uid, folder, remove_labels)
                if success:
                    results.append(f"Removed labels: {', '.join(remove_labels)}")
                else:
                    results.append(
                        f"Failed to remove labels: {', '.join(remove_labels)}"
                    )

            if not results:
                return "No label changes requested"

            return "; ".join(results)
        except Exception as e:
            logger.error(f"Error modifying Gmail labels: {e}")
            return f"Error: {e}"

    # Get attachment content tool
    @mcp.tool()
    async def get_attachment_content(
        folder: str,
        uid: int,
        filename: str,
        ctx: Context,
    ) -> str:
        """Extract text content from an email attachment.
        Supports PDF, DOCX, and text-based files.

        Args:
            folder: Folder name
            uid: Email UID
            filename: Name of the attachment
            ctx: MCP context

        Returns:
            Extracted text content or error message
        """
        import io

        client = get_client_from_context(ctx)

        try:
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return "Error: Email not found"

            # Find the attachment
            attachment = next(
                (a for a in email_obj.attachments if a.filename == filename), None
            )

            if not attachment:
                available = [a.filename for a in email_obj.attachments]
                return f"Error: Attachment '{filename}' not found. Available: {', '.join(available)}"

            # If using Gmail and attachment data is missing, fetch it
            if (
                not attachment.content
                and hasattr(client, "get_attachment_data")
                and hasattr(attachment, "attachment_id")
                and attachment.attachment_id
            ):
                try:
                    attachment.content = client.get_attachment_data(
                        email_obj.message_id, attachment.attachment_id
                    )
                except Exception as e:
                    return f"Error fetching Gmail attachment: {e}"

            if not attachment.content:
                return "Error: Attachment has no content"

            content_type = attachment.content_type.lower()

            # Handle different content types
            if content_type == "application/pdf":
                try:
                    import pypdf

                    reader = pypdf.PdfReader(io.BytesIO(attachment.content))
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    return text.strip() or "[No text could be extracted from PDF]"
                except ImportError:
                    return "Error: pypdf library not installed on server"
                except Exception as e:
                    return f"Error parsing PDF: {e}"

            elif (
                content_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                or filename.lower().endswith(".docx")
            ):
                try:
                    import docx

                    doc = docx.Document(io.BytesIO(attachment.content))
                    text = "\n".join([p.text for p in doc.paragraphs])
                    return text.strip() or "[No text could be extracted from DOCX]"
                except ImportError:
                    return "Error: python-docx library not installed on server"
                except Exception as e:
                    return f"Error parsing DOCX: {e}"

            elif content_type.startswith("text/") or filename.lower().endswith(
                (".txt", ".log", ".md", ".json", ".csv")
            ):
                try:
                    # Try to decode as utf-8
                    return attachment.content.decode("utf-8", errors="replace")
                except Exception as e:
                    return f"Error decoding text: {e}"

            else:
                return f"Error: Unsupported content type '{content_type}' for text extraction"

        except Exception as e:
            logger.error(f"Error getting attachment content: {e}")
            return f"Error: {e}"

    # Flag email
    @mcp.tool()
    async def flag_email(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Flag an email.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Success message
        """
        client = get_client_from_context(ctx)
        try:
            client.mark_email(uid, folder, r"\Flagged", True)
            return "Email flagged"
        except Exception as e:
            logger.error(f"Error flagging email: {e}")
            return f"Error: {e}"

    # Delete email
    @mcp.tool()
    async def delete_email(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Delete an email.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Success message
        """
        client = get_client_from_context(ctx)
        try:
            client.delete_email(uid, folder)
            return "Email deleted"
        except Exception as e:
            logger.error(f"Error deleting email: {e}")
            return f"Error: {e}"

    # Process email with multiple actions
    @mcp.tool()
    async def process_email(
        folder: str,
        uid: int,
        action: str,
        notes: Optional[str] = None,
        target_folder: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Process an email with one or more actions.

        Args:
            folder: Folder name
            uid: Email UID
            action: Action to take (move, read, unread, flag, unflag, delete)
            notes: Optional notes about the decision
            target_folder: Target folder for move action
            ctx: MCP context

        Returns:
            Success message or error message
        """
        client = get_client_from_context(ctx)

        # Process the action
        result = ""
        try:
            if action.lower() == "move":
                if not target_folder:
                    return "Target folder must be specified for move action"
                client.move_email(uid, folder, target_folder)
                result = f"Email moved from {folder} to {target_folder}"
            elif action.lower() == "read":
                client.mark_email(uid, folder, r"\Seen", True)
                result = "Email marked as read"
            elif action.lower() == "unread":
                client.mark_email(uid, folder, r"\Seen", False)
                result = "Email marked as unread"
            elif action.lower() == "flag":
                client.mark_email(uid, folder, r"\Flagged", True)
                result = "Email flagged"
            elif action.lower() == "unflag":
                client.mark_email(uid, folder, r"\Flagged", False)
                result = "Email unflagged"
            elif action.lower() == "delete":
                client.delete_email(uid, folder)
                result = "Email deleted"
            else:
                return f"Invalid action: {action}"

            return result
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            return f"Error: {e}"

    # Create a task from an email
    @mcp.tool()
    async def create_task(
        description: str,
        priority: str = "medium",
        due_date: Optional[str] = None,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Create a task in the tasks list.

        Args:
            description: Task description
            priority: Task priority (low, medium, high)
            due_date: Optional due date (YYYY-MM-DD)
            ctx: MCP context

        Returns:
            Success message
        """
        if not description:
            return "Error: Description is required"

        if priority not in ["low", "medium", "high"]:
            return (
                f"Error: Invalid priority '{priority}'. Must be low, medium, or high."
            )

        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except ValueError:
                return f"Error: Invalid due date format '{due_date}'. Use YYYY-MM-DD."

        task_entry = f"- [ ] {description} (Priority: {priority}"
        if due_date:
            task_entry += f", Due: {due_date}"
        task_entry += ")\n"

        # Use absolute path for tasks.md to be more robust
        import os

        tasks_file = os.path.join(os.getcwd(), "tasks.md")

        try:
            with open(tasks_file, "a") as f:
                f.write(task_entry)
            logger.info(f"Created task: {description}")
            return f"Success: Task created: {description}"
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            return f"Error: {e}"

    # Setup Smart Secretary labels/folders
    @mcp.tool()
    async def setup_smart_labels(
        ctx: Context,
        dry_run: bool = False,
    ) -> str:
        """Setup the 'Smart Secretary' folder hierarchy for organizing emails.
        Folders to be created:
        - Secretary/Priority (Immediate attention)
        - Secretary/Action-Required (Tasks identified)
        - Secretary/Processed (AI handled)
        - Secretary/Calendar (Meeting invites)
        - Secretary/Newsletter (Low priority)
        - Secretary/Waiting (Pending others)

        Args:
            ctx: MCP context
            dry_run: If True, only check which folders would be created.

        Returns:
            Success or status message.
        """
        client = get_client_from_context(ctx)

        labels = [
            "Secretary/Priority",
            "Secretary/Action-Required",
            "Secretary/Processed",
            "Secretary/Calendar",
            "Secretary/Newsletter",
            "Secretary/Waiting",
        ]

        try:
            # Ensure folder cache is fresh
            client.list_folders(refresh=True)

            results = []
            for label in labels:
                exists = client.folder_exists(label)
                if exists:
                    results.append(f"[Exists] {label}")
                else:
                    if dry_run:
                        results.append(f"[Pending] {label} (Dry Run)")
                    else:
                        success = client.create_folder(label)
                        if success:
                            results.append(f"[Created] {label}")
                        else:
                            results.append(f"[Failed] {label}")

            return "\n".join(results)
        except Exception as e:
            logger.error(f"Error setting up smart labels: {e}")
            return f"Error: {e}"

    # Get unread messages tool
    @mcp.tool()
    async def get_unread_messages(
        folder: str = "INBOX",
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "date",
        sort_order: str = "desc",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get unread messages from a folder.

        Args:
            folder: Folder name
            limit: Maximum number of messages to return
            offset: Number of messages to skip
            sort_by: Field to sort by (date, subject, from)
            sort_order: Sort order (asc, desc)
            ctx: MCP context

        Returns:
            JSON string with unread messages
        """
        client = get_client_from_context(ctx)

        try:
            # Use the refined method in ImapClient
            emails = client.get_unread_messages(
                folder=folder,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order,
            )

            if not emails:
                return json.dumps([], indent=2)

            # Format results
            results = []
            for email_obj in emails.values():
                results.append(
                    {
                        "uid": email_obj.uid,
                        "from": str(email_obj.from_),
                        "subject": email_obj.subject,
                        "date": email_obj.date.isoformat() if email_obj.date else None,
                        "snippet": email_obj.get_snippet(100),
                    }
                )

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error getting unread messages: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    # Process meeting invite and generate a draft reply
    @mcp.tool()
    async def process_meeting_invite(
        folder: str,
        uid: int,
        ctx: Context,
        availability_mode: str = "random",
    ) -> dict:
        """Process a meeting invite email and create a draft reply.

        This tool orchestrates the full workflow:
        1. Identifies if the email is a meeting invite
        2. Checks calendar availability for the meeting time
        3. Generates an appropriate reply (accept/decline)
        4. Creates a MIME message for the reply
        5. Saves the reply as a draft

        Args:
            folder: Folder containing the invite email
            uid: UID of the invite email
            ctx: MCP context
            availability_mode: Mode for availability check (random, always_available,
                              always_busy, business_hours, weekdays)

        Returns:
            Dictionary with the processing result:
              - status: "success", "not_invite", or "error"
              - message: Description of the result
              - draft_uid: UID of the saved draft (if successful)
              - draft_folder: Folder where the draft was saved (if successful)
              - availability: Whether the time slot was available
        """
        from workspace_secretary.workflows.invite_parser import identify_meeting_invite_details
        from workspace_secretary.workflows.calendar_mock import check_mock_availability
        from workspace_secretary.workflows.meeting_reply import generate_meeting_reply_content
        from workspace_secretary.smtp_client import create_reply_mime
        from workspace_secretary.models import EmailAddress

        client = get_client_from_context(ctx)
        result = {
            "status": "error",
            "message": "An error occurred during processing",
            "draft_uid": None,
            "draft_folder": None,
            "availability": None,
        }

        try:
            # Step 1: Fetch the original email
            logger.info(f"Fetching email UID {uid} from folder {folder}")
            email_obj = client.fetch_email(uid, folder)

            if not email_obj:
                result["message"] = f"Email with UID {uid} not found in folder {folder}"
                return result

            # Step 2: Identify if it's a meeting invite
            logger.info(
                f"Analyzing email for meeting invite details: {email_obj.subject}"
            )
            invite_result = identify_meeting_invite_details(email_obj)

            if not invite_result["is_invite"]:
                result["status"] = "not_invite"
                result["message"] = "The email is not a meeting invite"
                return result

            invite_details = invite_result["details"]

            # Step 3: Check calendar availability
            logger.info(
                f"Checking calendar availability for meeting: {invite_details['subject']}"
            )
            availability_result = check_mock_availability(
                invite_details.get("start_time"),
                invite_details.get("end_time"),
                availability_mode,
            )

            result["availability"] = availability_result["available"]

            # Step 4: Generate reply content
            logger.info(
                f"Generating {'accept' if availability_result['available'] else 'decline'} reply"
            )
            reply_content = generate_meeting_reply_content(
                invite_details, availability_result
            )

            # Step 5: Create MIME message
            # Determine sender (reply_from)
            reply_from = EmailAddress(name="Me", address=client.config.username)

            mime_message = create_reply_mime(
                original_email=email_obj,
                reply_to=reply_from,
                body=reply_content["reply_body"],
                subject=reply_content["reply_subject"],
                reply_all=False,
            )

            # Step 6: Save as draft
            logger.info("Saving reply as draft")
            draft_uid = client.save_draft_mime(mime_message)

            if draft_uid:
                result["status"] = "success"
                result["message"] = (
                    f"Processed invite and saved {'accept' if availability_result['available'] else 'decline'} "
                    f"reply as draft (UID: {draft_uid})"
                )
                result["draft_uid"] = str(draft_uid)
                result["draft_folder"] = client._get_drafts_folder()
            else:
                result["status"] = "error"
                result["message"] = "Failed to save draft"

            return result

        except Exception as e:
            logger.error(f"Error processing meeting invite: {e}")
            result["message"] = f"Error: {str(e)}"
            return result

    # --- Calendar Tools ---

    @mcp.tool()
    async def list_calendar_events(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """List upcoming events from Google Calendar.

        Args:
            time_min: ISO format start time (e.g. 2024-01-01T00:00:00Z)
            time_max: ISO format end time
            calendar_id: Calendar identifier
            ctx: MCP context

        Returns:
            JSON list of calendar events
        """
        client = get_calendar_client_from_context(ctx)
        try:
            events = client.list_events(time_min, time_max, calendar_id)
            return json.dumps(events, indent=2)
        except Exception as e:
            logger.error(f"Error listing calendar events: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def create_calendar_event(
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary",
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Create a new event on Google Calendar.

        Args:
            summary: Title of the event
            start_time: ISO format start time (e.g. 2024-01-01T10:00:00Z)
            end_time: ISO format end time
            description: Detailed description
            location: Event location
            calendar_id: Calendar identifier
            ctx: MCP context

        Returns:
            JSON representation of created event
        """
        client = get_calendar_client_from_context(ctx)
        event_data = {
            "summary": summary,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        if description:
            event_data["description"] = description
        if location:
            event_data["location"] = location

        try:
            event = client.create_event(event_data, calendar_id)
            return json.dumps(event, indent=2)
        except Exception as e:
            logger.error(f"Error creating calendar event: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def gmail_search(
        query: str,
        max_results: int = 20,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Search emails using native Gmail search syntax.
        Example queries: 'has:attachment', 'from:boss is:unread', 'after:2024/01/01'.

        Args:
            query: Gmail search query string
            max_results: Max results to return
            ctx: MCP context

        Returns:
            JSON list of message summaries
        """
        client = get_gmail_client_from_context(ctx)
        try:
            messages = client.search_messages(query, max_results)
            results = []
            for m in messages:
                # Fetch minimal details for the list
                full_msg = client.get_message(m["id"])
                if full_msg:
                    results.append(
                        {
                            "id": full_msg.message_id,
                            "threadId": full_msg.gmail_thread_id,
                            "from": str(full_msg.from_),
                            "subject": full_msg.subject,
                            "date": full_msg.date.isoformat()
                            if full_msg.date
                            else None,
                            "labels": full_msg.gmail_labels,
                        }
                    )
            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error in gmail_search: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def gmail_get_thread(
        thread_id: str,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Get an entire conversation thread using Gmail API.

        Args:
            thread_id: Gmail thread identifier
            ctx: MCP context

        Returns:
            JSON list of emails in the thread
        """
        client = get_gmail_client_from_context(ctx)
        try:
            emails = client.get_thread(thread_id)
            results = []
            for e in emails:
                results.append(
                    {
                        "id": e.message_id,
                        "from": str(e.from_),
                        "subject": e.subject,
                        "date": e.date.isoformat() if e.date else None,
                        "content": e.content.get_best_content(),
                        "labels": e.gmail_labels,
                    }
                )
            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error in gmail_get_thread: {e}")
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    async def get_calendar_availability(
        time_min: str,
        time_max: str,
        ctx: Context = None,  # type: ignore
    ) -> str:
        """Check free/busy status for a time range.

        Args:
            time_min: ISO format start time
            time_max: ISO format end time
            ctx: MCP context

        Returns:
            JSON representation of availability
        """
        client = get_calendar_client_from_context(ctx)
        try:
            availability = client.get_availability(time_min, time_max)
            return json.dumps(availability, indent=2)
        except Exception as e:
            logger.error(f"Error getting calendar availability: {e}")
            return json.dumps({"error": str(e)}, indent=2)
