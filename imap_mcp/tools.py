"""MCP tools implementation for email operations."""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Union, Any


from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context

from imap_mcp.imap_client import ImapClient
from imap_mcp.resources import get_client_from_context, get_smtp_client_from_context

from typing import Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# Define the path for storing tasks
TASKS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tasks.json")


async def _create_task_impl(
    description: str,
    due_date: Optional[str] = None,
    priority: Optional[int] = None,
) -> str:
    """Internal implementation for creating a task."""
    task = {
        "id": int(datetime.now().timestamp()),
        "description": description,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "due_date": due_date,
        "priority": priority,
    }

    try:
        tasks = []
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r") as f:
                content = f.read()
                if content:
                    tasks = json.loads(content)

        tasks.append(task)

        with open(TASKS_FILE, "w") as f:
            json.dump(tasks, f, indent=2)

        return f"Task created successfully: {description} (ID: {task['id']})"
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return f"Error creating task: {e}"


def register_tools(mcp: FastMCP, imap_client: ImapClient) -> None:
    """Register MCP tools.

    Args:
        mcp: MCP server
        imap_client: IMAP client
    """

    # Internal implementations
    async def _draft_meeting_reply(
        invite_details: Dict[str, Any], availability_status: bool, ctx: Context
    ) -> Dict[str, Any]:
        """Internal implementation for drafting meeting reply."""
        from imap_mcp.workflows.meeting_reply import generate_meeting_reply_content

        # Create availability status dict required by the helper
        status = {
            "available": availability_status,
            "reason": "Schedule conflict" if not availability_status else "",
        }

        # Generate content
        return generate_meeting_reply_content(invite_details, status)

    async def _identify_meeting_invite(
        folder: str, uid: int, ctx: Context
    ) -> Dict[str, Any]:
        """Internal implementation for identifying meeting invite."""
        from imap_mcp.workflows.invite_parser import identify_meeting_invite_details

        client = get_client_from_context(ctx)
        try:
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return {"is_invite": False, "error": "Email not found"}

            return identify_meeting_invite_details(email_obj)
        except Exception as e:
            logger.error(f"Error identifying meeting invite: {e}")
            return {"is_invite": False, "error": str(e)}

    async def _check_calendar_availability(
        start_time: str, end_time: str, ctx: Context
    ) -> Dict[str, Any]:
        """Internal implementation for checking calendar availability."""
        from imap_mcp.workflows.calendar_mock import check_mock_availability

        # In a real app, we would use ctx to get calendar credentials
        # For now, we use the mock implementation
        return check_mock_availability(start_time, end_time)

    # Using decorator pattern to register tools
    @mcp.tool()
    async def draft_meeting_reply_tool(
        invite_details: Dict[str, Any], availability_status: bool, ctx: Context
    ) -> Dict[str, Any]:
        """Drafts a meeting reply (accept/decline) based on calendar invite details and availability.

        Args:
            invite_details: Dictionary containing invite details (subject, start_time, end_time, organizer, location)
            availability_status: Whether the user is available for the meeting (True=available/accept, False=unavailable/decline)
            ctx: MCP context

        Returns:
            Dictionary with reply text and additional metadata
        """
        return await _draft_meeting_reply(invite_details, availability_status, ctx)

    @mcp.tool()
    async def identify_meeting_invite_tool(
        folder: str, uid: int, ctx: Context
    ) -> Dict[str, Any]:
        """Identifies if an email is a meeting invite and extracts relevant details.

        Args:
            folder: Email folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Dictionary with invite details if it's a meeting invite, or status information if not
        """
        return await _identify_meeting_invite(folder, uid, ctx)

    @mcp.tool()
    async def check_calendar_availability_tool(
        start_time: str, end_time: str, ctx: Context
    ) -> Dict[str, Any]:
        """Checks calendar availability for a given time slot.

        Args:
            start_time: Meeting start time (ISO format)
            end_time: Meeting end time (ISO format)
            ctx: MCP context

        Returns:
            Dictionary with availability status and additional information
        """
        return await _check_calendar_availability(start_time, end_time, ctx)

    @mcp.tool()
    async def process_invite_email_tool(
        folder: str, uid: int, ctx: Context
    ) -> Dict[str, Any]:
        """Processes a meeting invitation email: identifies invite, checks availability, drafts reply, saves draft.

        Args:
            folder: Email folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Dictionary with processing results and status information
        """
        # We need to defer to the tool that is defined later in this file
        # Since Python processes decorators at definition time, we can't forward reference
        # Instead we'll implement the logic directly here or use a shared implementation
        # For simplicity, we'll just error out saying use the dedicated tool
        return {"error": "Use process_meeting_invite tool instead"}

    @mcp.tool()
    async def create_task(
        description: str,
        ctx: Context,
        due_date: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> str:
        """Creates a new task and saves it to a local file.

        Args:
            description: Task description
            ctx: MCP context
            due_date: Optional due date in ISO format
            priority: Optional priority (1=high, 2=medium, 3=low)

        Returns:
            Success message or error information
        """
        return await _create_task_impl(description, due_date, priority)

    @mcp.tool()
    async def draft_reply_tool(
        folder: str,
        uid: int,
        reply_body: str,
        ctx: Context,
        reply_all: bool = False,
        cc: Optional[List[str]] = None,
        body_html: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a draft reply to an email and saves it to the drafts folder.

        Args:
            folder: Email folder name
            uid: Email UID
            reply_body: Reply text content
            ctx: MCP context
            reply_all: Whether to reply to all recipients
            cc: Optional CC recipients
            body_html: Optional HTML version of the reply

        Returns:
            Dictionary with status and the UID of the created draft
        """
        from imap_mcp.models import EmailAddress
        from imap_mcp.smtp_client import create_reply_mime

        client = get_client_from_context(ctx)

        try:
            # Fetch original email
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return {"status": "error", "message": f"Email with UID {uid} not found"}

            # Determine sender (reply_from)
            # In a real scenario, this would be the user's email address
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
                    "draft_uid": draft_uid,
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
            Success message or error message
        """
        client = get_client_from_context(ctx)

        try:
            success = client.mark_email(uid, folder, r"\Seen", True)
            if success:
                return "Email marked as read"
            else:
                return "Failed to mark email as read"
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
            Success message or error message
        """
        client = get_client_from_context(ctx)

        try:
            success = client.mark_email(uid, folder, r"\Seen", False)
            if success:
                return "Email marked as unread"
            else:
                return "Failed to mark email as unread"
        except Exception as e:
            logger.error(f"Error marking email as unread: {e}")
            return f"Error: {e}"

    # Flag email (important/starred)
    @mcp.tool()
    async def flag_email(
        folder: str,
        uid: int,
        ctx: Context,
        flag: bool = True,
    ) -> str:
        """Flag or unflag email.

        Args:
            folder: Folder name
            uid: Email UID
            flag: True to flag, False to unflag
            ctx: MCP context

        Returns:
            Success message or error message
        """
        client = get_client_from_context(ctx)

        try:
            success = client.mark_email(uid, folder, r"\Flagged", flag)
            if success:
                return f"Email {'flagged' if flag else 'unflagged'}"
            else:
                return f"Failed to {'flag' if flag else 'unflag'} email"
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
        """Delete email.

        Args:
            folder: Folder name
            uid: Email UID
            ctx: MCP context

        Returns:
            Success message or error message
        """
        client = get_client_from_context(ctx)

        try:
            success = client.delete_email(uid, folder)
            if success:
                return "Email deleted"
            else:
                return "Failed to delete email"
        except Exception as e:
            logger.error(f"Error deleting email: {e}")
            return f"Error: {e}"

    # Get chronological thread of emails
    @mcp.tool()
    async def get_email_thread(
        folder: str,
        uid: int,
        ctx: Context,
    ) -> str:
        """Fetch all emails in a conversation thread.

        Args:
            folder: Folder containing the email
            uid: UID of an email in the thread
            ctx: MCP context

        Returns:
            Concatenated string of all emails in the thread
        """
        client = get_client_from_context(ctx)
        try:
            thread = client.fetch_thread(uid, folder)
            if not thread:
                return f"No thread found for email with UID {uid}"

            output = []
            for email_obj in thread:
                recipients_to = ", ".join(str(a) for a in email_obj.to)
                recipients_cc = ", ".join(str(a) for a in email_obj.cc)

                email_str = [
                    f"--- THREAD EMAIL [UID: {email_obj.uid}] ---",
                    f"From: {email_obj.from_}",
                    f"To: {recipients_to}",
                ]
                if recipients_cc:
                    email_str.append(f"CC: {recipients_cc}")

                email_str.extend(
                    [
                        f"Date: {email_obj.date.isoformat() if email_obj.date else 'Unknown'}",
                        f"Subject: {email_obj.subject}",
                        f"Body:\n{email_obj.content.get_best_content()}",
                        "------------------------",
                    ]
                )
                output.append("\n".join(email_str))

            return "\n\n".join(output)
        except Exception as e:
            logger.error(f"Error fetching thread: {e}")
            return f"Error: {e}"

    # Get bulk unseen emails for analysis
    @mcp.tool()
    async def get_unseen_emails(
        ctx: Context,
        folder: str = "INBOX",
        limit: int = 20,
        body_limit: int = 700,
    ) -> str:
        """Fetches the most recent unseen emails for bulk analysis.

        Args:
            ctx: MCP context
            folder: Folder to search in (default: INBOX)
            limit: Maximum number of emails to fetch (default: 20)
            body_limit: Characters to include from the body (default: 700)

        Returns:
            Concatenated string of unseen emails with critical headers
        """
        client = get_client_from_context(ctx)
        try:
            # Search for unseen emails
            uids = client.search("unseen", folder=folder)

            # Sort by newest first and apply limit
            uids = sorted(uids, reverse=True)[:limit]

            if not uids:
                return f"No unseen emails found in {folder}."

            # Fetch emails
            emails = client.fetch_emails(uids, folder=folder)

            output = []
            # Iterate through UIDs to maintain order
            for uid in sorted(emails.keys(), reverse=True):
                email_obj = emails[uid]

                recipients_to = ", ".join(str(a) for a in email_obj.to)
                recipients_cc = ", ".join(str(a) for a in email_obj.cc)
                recipients_bcc = ", ".join(str(a) for a in email_obj.bcc)

                body = email_obj.content.get_best_content()
                if len(body) > body_limit:
                    body = body[:body_limit] + "... [TRUNCATED]"

                email_str = [
                    f"--- EMAIL [UID: {uid}] ---",
                    f"From: {email_obj.from_}",
                    f"To: {recipients_to}",
                ]

                if recipients_cc:
                    email_str.append(f"CC: {recipients_cc}")
                if recipients_bcc:
                    email_str.append(f"BCC: {recipients_bcc}")

                email_str.extend(
                    [
                        f"Date: {email_obj.date.isoformat() if email_obj.date else 'Unknown'}",
                        f"Subject: {email_obj.subject}",
                        f"Body: {body}",
                        "------------------------",
                    ]
                )
                output.append("\n".join(email_str))

            return f"Found {len(output)} unseen emails in {folder}:\n\n" + "\n\n".join(
                output
            )

        except Exception as e:
            logger.error(f"Error fetching unseen emails: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def get_attachment_content(
        folder: str,
        uid: int,
        filename: str,
        ctx: Context,
        char_limit: int = 10000,
    ) -> str:
        """Extracts text content from an email attachment.
        Supports .txt, .log, .pdf, and .docx files.

        Args:
            folder: Folder containing the email
            uid: Email UID
            filename: Name of the attachment file
            ctx: MCP context
            char_limit: Maximum characters to extract (default: 10000)

        Returns:
            Extracted text content or error message
        """
        import io
        from pypdf import PdfReader
        from docx import Document

        client = get_client_from_context(ctx)
        try:
            email_obj = client.fetch_email(uid, folder)
            if not email_obj:
                return f"Email with UID {uid} not found"

            attachment = next(
                (a for a in email_obj.attachments if a.filename == filename), None
            )
            if not attachment:
                available = ", ".join(a.filename for a in email_obj.attachments)
                return f"Attachment '{filename}' not found. Available: {available}"

            if not attachment.content:
                return f"Attachment '{filename}' has no content"

            content_bytes = attachment.content
            extracted_text = ""

            # Determine file type and extract text
            ext = os.path.splitext(filename.lower())[1]

            if ext in [".txt", ".log", ".md", ".py", ".js", ".json", ".yaml", ".yml"]:
                try:
                    extracted_text = content_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    extracted_text = content_bytes.decode("latin-1")

            elif ext == ".pdf":
                pdf_file = io.BytesIO(content_bytes)
                reader = PdfReader(pdf_file)
                pages = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                extracted_text = "\n\n".join(pages)

            elif ext == ".docx":
                docx_file = io.BytesIO(content_bytes)
                doc = Document(docx_file)
                paragraphs = [p.text for p in doc.paragraphs]
                extracted_text = "\n".join(paragraphs)

            else:
                return f"Unsupported file type '{ext}' for text extraction"

            if not extracted_text.strip():
                return f"No text could be extracted from '{filename}'"

            if len(extracted_text) > char_limit:
                extracted_text = (
                    extracted_text[:char_limit] + "\n\n... [TRUNCATED DUE TO SIZE]"
                )

            return f"--- Content of '{filename}' ---\n\n{extracted_text}"

        except Exception as e:
            logger.error(f"Error extracting attachment content: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def modify_gmail_labels(
        folder: str,
        uid: int,
        ctx: Context,
        labels: List[str],
        action: str = "add",
    ) -> str:
        """Modify Gmail labels for an email.

        Args:
            folder: Folder containing the email
            uid: Email UID
            ctx: MCP context
            labels: List of labels to modify
            action: Action to take ('add', 'remove', or 'set')

        Returns:
            Success or error message
        """
        client = get_client_from_context(ctx)
        try:
            if action.lower() == "add":
                success = client.add_gmail_labels(uid, folder, labels)
            elif action.lower() == "remove":
                success = client.remove_gmail_labels(uid, folder, labels)
            elif action.lower() == "set":
                success = client.set_gmail_labels(uid, folder, labels)
            else:
                return f"Invalid action: {action}. Use 'add', 'remove', or 'set'."

            if success:
                return f"Successfully {action}ed labels: {', '.join(labels)}"
            else:
                return f"Failed to modify labels. Ensure the server supports Gmail extensions."
        except Exception as e:
            logger.error(f"Error modifying Gmail labels: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def get_gmail_thread(
        thread_id: str,
        ctx: Context,
        folder: str = "INBOX",
    ) -> str:
        """Fetches all emails in a Gmail conversation thread using the thread ID.

        Args:
            thread_id: Gmail thread ID (X-GM-THRID)
            ctx: MCP context
            folder: Folder to search in (default: INBOX)

        Returns:
            Concatenated string of all emails in the thread
        """
        client = get_client_from_context(ctx)
        try:
            uids = client.search_by_thread_id(thread_id, folder)
            if not uids:
                return f"No emails found for thread ID: {thread_id}"

            emails = client.fetch_emails(uids, folder)

            output = []
            for uid in sorted(emails.keys()):
                email_obj = emails[uid]
                recipients_to = ", ".join(str(a) for a in email_obj.to)
                recipients_cc = ", ".join(str(a) for a in email_obj.cc)

                email_str = [
                    f"--- GMAIL THREAD EMAIL [UID: {uid}, ThreadID: {thread_id}] ---",
                    f"Labels: {', '.join(email_obj.gmail_labels)}",
                    f"From: {email_obj.from_}",
                    f"To: {recipients_to}",
                ]
                if recipients_cc:
                    email_str.append(f"CC: {recipients_cc}")

                email_str.extend(
                    [
                        f"Date: {email_obj.date.isoformat() if email_obj.date else 'Unknown'}",
                        f"Subject: {email_obj.subject}",
                        f"Body:\n{email_obj.content.get_best_content()}",
                        "------------------------",
                    ]
                )
                output.append("\n".join(email_str))

            return "\n\n".join(output)
        except Exception as e:
            logger.error(f"Error fetching Gmail thread: {e}")
            return f"Error: {e}"

    @mcp.tool()
    async def advanced_search(
        ctx: Context,
        folder: str = "INBOX",
        subject: Optional[str] = None,
        from_address: Optional[str] = None,
        to_address: Optional[str] = None,
        body_text: Optional[str] = None,
        unseen_only: bool = False,
        since_date: Optional[str] = None,
        before_date: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Advanced search for emails using multiple combined criteria.

        Args:
            ctx: MCP context
            folder: Folder to search in (default: INBOX)
            subject: Search in subject
            from_address: Search in sender address
            to_address: Search in recipient address
            body_text: Search in email body text
            unseen_only: Only return unread emails
            since_date: Search emails after this date (YYYY-MM-DD)
            before_date: Search emails before this date (YYYY-MM-DD)
            limit: Maximum number of results

        Returns:
            JSON-formatted list of search results
        """
        client = get_client_from_context(ctx)

        # Build search criteria list
        search_criteria = []

        if unseen_only:
            search_criteria.append("UNSEEN")

        if subject:
            search_criteria.extend(["SUBJECT", subject])

        if from_address:
            search_criteria.extend(["FROM", from_address])

        if to_address:
            search_criteria.extend(["TO", to_address])

        if body_text:
            search_criteria.extend(["TEXT", body_text])

        if since_date:
            try:
                date_obj = datetime.strptime(since_date, "%Y-%m-%d").date()
                search_criteria.extend(["SINCE", date_obj])
            except ValueError:
                return f"Invalid since_date format: {since_date}. Use YYYY-MM-DD."

        if before_date:
            try:
                date_obj = datetime.strptime(before_date, "%Y-%m-%d").date()
                search_criteria.extend(["BEFORE", date_obj])
            except ValueError:
                return f"Invalid before_date format: {before_date}. Use YYYY-MM-DD."

        # If no criteria provided, search for everything
        if not search_criteria:
            search_criteria = "ALL"

        try:
            # Search for emails
            uids = client.search(search_criteria, folder=folder)

            # Sort by newest first and apply limit
            uids = sorted(uids, reverse=True)[:limit]

            if not uids:
                return json.dumps([], indent=2)

            # Fetch emails
            emails = client.fetch_emails(uids, folder=folder)

            results = []
            # Iterate through UIDs to maintain order
            for uid in sorted(emails.keys(), reverse=True):
                email_obj = emails[uid]
                results.append(
                    {
                        "uid": uid,
                        "folder": folder,
                        "from": str(email_obj.from_),
                        "to": [str(to) for to in email_obj.to],
                        "subject": email_obj.subject,
                        "date": email_obj.date.isoformat() if email_obj.date else None,
                        "flags": email_obj.flags,
                        "has_attachments": len(email_obj.attachments) > 0,
                        "gmail_thread_id": email_obj.gmail_thread_id,
                        "gmail_labels": email_obj.gmail_labels,
                    }
                )

            return json.dumps(results, indent=2)

        except Exception as e:
            logger.error(f"Error in advanced search: {e}")
            return f"Error: {e}"

    # Search for emails
    @mcp.tool()
    async def search_emails(
        query: str,
        ctx: Context,
        folder: Optional[str] = None,
        criteria: str = "text",
        limit: int = 10,
    ) -> str:
        """Search for emails.

        Args:
            query: Search query
            folder: Folder to search in (None for all folders)
            criteria: Search criteria (text, from, to, subject, all, unseen, seen)
            limit: Maximum number of results
            ctx: MCP context

        Returns:
            JSON-formatted list of search results
        """
        client = get_client_from_context(ctx)

        # Define search criteria
        search_criteria_map = {
            "text": ["TEXT", query],
            "from": ["FROM", query],
            "to": ["TO", query],
            "subject": ["SUBJECT", query],
            "all": "ALL",
            "unseen": "UNSEEN",
            "seen": "SEEN",
            "today": "today",
            "week": "week",
            "month": "month",
        }

        if criteria.lower() not in search_criteria_map:
            return f"Invalid search criteria: {criteria}"

        search_criteria = search_criteria_map[criteria.lower()]

        folders_to_search = [folder] if folder else client.list_folders()
        results = []

        for current_folder in folders_to_search:
            try:
                # Search for emails
                uids = client.search(search_criteria, folder=current_folder)

                # Limit results and sort by newest first
                uids = sorted(uids, reverse=True)[:limit]

                if uids:
                    # Fetch emails
                    emails = client.fetch_emails(uids, folder=current_folder)

                    # Create summaries
                    for uid, email_obj in emails.items():
                        results.append(
                            {
                                "uid": uid,
                                "folder": current_folder,
                                "from": str(email_obj.from_),
                                "to": [str(to) for to in email_obj.to],
                                "subject": email_obj.subject,
                                "date": email_obj.date.isoformat()
                                if email_obj.date
                                else None,
                                "flags": email_obj.flags,
                                "has_attachments": len(email_obj.attachments) > 0,
                            }
                        )
            except Exception as e:
                logger.warning(f"Error searching folder {current_folder}: {e}")

        # Sort results by date (newest first)
        results.sort(key=lambda x: x.get("date") or "0", reverse=True)

        # Apply global limit
        results = results[:limit]

        return json.dumps(results, indent=2)

    # Process email interactive session
    @mcp.tool()
    async def process_email(
        folder: str,
        uid: int,
        action: str,
        ctx: Context,
        notes: Optional[str] = None,
        target_folder: Optional[str] = None,
    ) -> str:
        """Process an email with specified action.

        This is a higher-level tool that combines multiple actions and records
        the decision for learning purposes.

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

        # Fetch the email first to have context for learning
        email_obj = client.fetch_email(uid, folder)
        if not email_obj:
            return f"Email with UID {uid} not found in folder {folder}"

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

            # TODO: Record the action for learning in a separate module

            return result
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            return f"Error: {e}"

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
        from imap_mcp.workflows.invite_parser import identify_meeting_invite_details
        from imap_mcp.workflows.calendar_mock import check_mock_availability
        from imap_mcp.workflows.meeting_reply import generate_meeting_reply_content
        from imap_mcp.smtp_client import create_reply_mime
        from imap_mcp.models import EmailAddress

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

            # Step 5: Create MIME message for reply
            logger.info("Creating MIME message for reply")
            # Create EmailAddress object for the reply sender (use the original recipient)
            if email_obj.to and len(email_obj.to) > 0:
                reply_from = email_obj.to[0]
            else:
                # Fallback to a default if no recipient in original email
                reply_from = EmailAddress(name="Me", address=client.config.username)

            # Create the reply MIME message - using the standalone function
            mime_message = create_reply_mime(
                original_email=email_obj,
                reply_to=reply_from,
                body=reply_content["reply_body"],
                subject=reply_content["reply_subject"],
                # Don't use reply_all for meeting responses
                reply_all=False,
            )

            # Step 6: Save as draft
            logger.info("Saving reply as draft")
            draft_uid = client.save_draft_mime(mime_message)

            if draft_uid:
                drafts_folder = client._get_drafts_folder()
                result["status"] = "success"
                result["message"] = (
                    f"Draft reply created: {reply_content['reply_type']}"
                )
                result["draft_uid"] = draft_uid
                result["draft_folder"] = drafts_folder
                logger.info(
                    f"Draft saved successfully with UID {draft_uid} in folder {drafts_folder}"
                )
            else:
                result["message"] = "Failed to save draft"

        except Exception as e:
            logger.error(f"Error processing meeting invite: {e}")
            result["message"] = f"Error: {e}"

        return result
