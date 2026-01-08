"""Gmail API client for the AI Secretary."""

import logging
import base64
from typing import Any, Dict, List, Optional, Union, cast
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from workspace_secretary.config import ServerConfig
from workspace_secretary.models import Email, EmailAddress, EmailContent, EmailAttachment

logger = logging.getLogger(__name__)


class GmailClient:
    """Client for interacting with Gmail REST API."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.service = None
        self._creds = None

    def _get_credentials(self) -> Optional[Credentials]:
        """Convert our OAuth2Config to Google Credentials."""
        if not self.config.imap.oauth2:
            logger.error("OAuth2 configuration missing for Gmail API")
            return None

        oauth = self.config.imap.oauth2
        creds = Credentials(
            token=oauth.access_token,
            refresh_token=oauth.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            scopes=[
                "https://mail.google.com/",
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        )

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        return creds

    def connect(self):
        """Initialize the Gmail service."""
        try:
            creds = self._get_credentials()
            if not creds:
                raise ValueError("Could not obtain credentials for Gmail API")

            self.service = build("gmail", "v1", credentials=creds)
            logger.info("Successfully connected to Gmail REST API")
        except Exception as e:
            logger.error(f"Failed to connect to Gmail API: {e}")
            raise

    def search_messages(
        self, query: str, max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for messages using Gmail search syntax."""
        if not self.service:
            self.connect()

        service = cast(Any, self.service)
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        return results.get("messages", [])

    def get_message(self, message_id: str) -> Optional[Email]:
        """Fetch a full message by ID and convert to our Email model."""
        if not self.service:
            self.connect()

        # Added for type safety
        service = cast(Any, self.service)
        msg_raw = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        return self._parse_gmail_message(msg_raw)

    def get_attachment_data(self, message_id: str, attachment_id: str) -> bytes:
        """Fetch raw attachment data from Gmail."""
        if not self.service:
            self.connect()

        service = cast(Any, self.service)
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

        data = attachment.get("data", "")
        if not data:
            return b""

        return base64.urlsafe_b64decode(data)

    def get_attachment_data(self, message_id: str, attachment_id: str) -> bytes:
        """Fetch raw attachment data from Gmail."""
        if not self.service:
            self.connect()

        attachment = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )

        data = attachment.get("data", "")
        if not data:
            return b""

        return base64.urlsafe_b64decode(data)

    def _parse_gmail_message(self, msg_raw: Dict[str, Any]) -> Email:
        """Parse Gmail API message resource into our Email model."""
        headers_list = msg_raw.get("payload", {}).get("headers", [])
        headers = {h["name"]: h["value"] for h in headers_list}

        # Parse basic fields
        subject = headers.get("Subject", "(No Subject)")
        from_str = headers.get("From", "")
        to_str = headers.get("To", "")
        cc_str = headers.get("Cc", "")
        date_str = headers.get("Date", "")

        # Parse Date
        date = None
        if date_str:
            try:
                import email.utils

                date = email.utils.parsedate_to_datetime(date_str)
            except:
                pass

        # Content and Attachments
        content = EmailContent()
        attachments = []

        def walk_parts(parts):
            for part in parts:
                mime_type = part.get("mimeType")
                body = part.get("body", {})
                data = body.get("data")

                if mime_type == "text/plain" and data:
                    text = base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="replace"
                    )
                    if not content.text:
                        content.text = text
                elif mime_type == "text/html" and data:
                    html = base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="replace"
                    )
                    if not content.html:
                        content.html = html
                elif part.get("filename"):
                    attachments.append(
                        EmailAttachment(
                            filename=part.get("filename"),
                            content_type=mime_type,
                            size=body.get("size", 0),
                            content_id=part.get(
                                "headers", [{"name": "Content-ID", "value": ""}]
                            )[0]
                            .get("value", "")
                            .strip("<>"),
                            content=None,  # We'll fetch on demand
                            attachment_id=body.get(
                                "attachmentId"
                            ),  # Store attachmentId
                        )
                    )

                if "parts" in part:
                    walk_parts(part["parts"])

        payload = msg_raw.get("payload", {})
        if "parts" in payload:
            walk_parts(payload["parts"])
        else:
            # Single part message
            data = payload.get("body", {}).get("data")
            if data:
                text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                if payload.get("mimeType") == "text/html":
                    content.html = text
                else:
                    content.text = text

        return Email(
            message_id=msg_raw.get("id", ""),
            subject=subject,
            from_=EmailAddress.parse(from_str),
            to=[EmailAddress.parse(t.strip()) for t in to_str.split(",") if t.strip()],
            cc=[EmailAddress.parse(c.strip()) for c in cc_str.split(",") if c.strip()],
            date=date,
            content=content,
            attachments=attachments,
            flags=[],  # Map labels to flags if needed
            headers=headers,
            folder=None,
            uid=None,
            gmail_thread_id=msg_raw.get("threadId"),
            gmail_labels=msg_raw.get("labelIds", []),
        )

    def modify_labels(
        self, message_id: str, add_labels: List[str], remove_labels: List[str]
    ):
        """Modify labels on a message."""
        if not self.service:
            self.connect()

        service = cast(Any, self.service)
        body = {"addLabelIds": add_labels, "removeLabelIds": remove_labels}
        return (
            service.users()
            .messages()
            .batchModify(userId="me", ids=[message_id], body=body)
            .execute()
        )

    def get_thread(self, thread_id: str) -> List[Email]:
        """Fetch an entire thread and return as a list of Emails."""
        if not self.service:
            self.connect()

        service = cast(Any, self.service)
        thread = service.users().threads().get(userId="me", id=thread_id).execute()

        return [self._parse_gmail_message(m) for m in thread.get("messages", [])]
