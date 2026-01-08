"""Pytest fixtures for IMAP MCP tests."""

import datetime
import email
import email.utils
import os
import re
import time
import logging
import base64
from contextlib import contextmanager
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Generator
from unittest.mock import MagicMock, patch

import pytest

from workspace_secretary.models import Email, EmailAddress, EmailAttachment, EmailContent
from workspace_secretary.config import ImapConfig, OAuth2Config, ServerConfig, CalendarConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_oauth2_config():
    """Create a mock OAuth2 configuration."""
    return OAuth2Config(
        client_id="mock_client_id",
        client_secret="mock_client_secret",
        refresh_token="mock_refresh_token",
        access_token="mock_access_token",
    )


@pytest.fixture
def mock_imap_config(mock_oauth2_config):
    """Create a mock IMAP configuration."""
    return ImapConfig(
        host="imap.gmail.com",
        port=993,
        username="test@gmail.com",
        use_ssl=True,
        oauth2=mock_oauth2_config,
    )


@pytest.fixture
def mock_calendar_config():
    """Create a mock Calendar configuration."""
    return CalendarConfig(enabled=True, verified_client="Thunderbird")


@pytest.fixture
def mock_server_config(mock_imap_config, mock_calendar_config):
    """Create a mock Server configuration."""
    return ServerConfig(
        imap=mock_imap_config,
        calendar=mock_calendar_config,
        allowed_folders=["INBOX", "Sent", "Drafts"],
    )


@pytest.fixture
def mock_gmail_service():
    """Create a mock Gmail API service with common responses."""
    with patch("googleapiclient.discovery.build") as mock_build:
        service = MagicMock()
        mock_build.return_value = service

        messages = service.users().messages()
        threads = service.users().threads()

        # Default list response
        messages.list().execute.return_value = {
            "messages": [{"id": "msg123", "threadId": "thread123"}],
            "resultSizeEstimate": 1,
        }

        # Default message get response
        def get_message_mock(userId, id, format=None):
            mock_exe = MagicMock()
            mock_exe.execute.return_value = {
                "id": id,
                "threadId": "thread123",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": f"Snippet for {id}",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": f"Subject for {id}"},
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "To", "value": "test@gmail.com"},
                        {"name": "Date", "value": "Thu, 1 Jan 2024 12:00:00 +0000"},
                        {"name": "Message-ID", "value": f"<{id}@example.com>"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(b"Hello world").decode()},
                },
            }
            return mock_exe

        messages.get.side_effect = get_message_mock

        # Default thread get response
        threads.get().execute.return_value = {
            "id": "thread123",
            "messages": [
                {
                    "id": "msg123",
                    "threadId": "thread123",
                    "payload": {
                        "headers": [{"name": "Subject", "value": "Thread Subject"}],
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"Msg 1").decode()},
                    },
                }
            ],
        }

        yield service


@pytest.fixture
def mock_calendar_service():
    """Create a mock Calendar API service with common responses."""
    with patch("googleapiclient.discovery.build") as mock_build:
        service = MagicMock()
        mock_build.return_value = service

        events = service.events()
        freebusy = service.freebusy()

        # Default list events
        events.list().execute.return_value = {
            "items": [
                {
                    "id": "evt123",
                    "summary": "Mock Event",
                    "start": {"dateTime": "2024-01-01T10:00:00Z"},
                    "end": {"dateTime": "2024-01-01T11:00:00Z"},
                }
            ]
        }

        # Default insert
        events.insert().execute.return_value = {
            "id": "new_evt_123",
            "htmlLink": "https://calendar.google.com/event?id=new_evt_123",
        }

        # Default freebusy
        freebusy.query().execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2024-01-01T12:00:00Z", "end": "2024-01-01T13:00:00Z"}
                    ]
                }
            }
        }

        yield service


@pytest.fixture
def test_email_message_simple():
    """Create a simple test email message."""
    msg = MIMEText("This is a simple test email.")
    msg["From"] = "Test Sender <sender@example.com>"
    msg["To"] = "Test Recipient <recipient@example.com>"
    msg["Subject"] = "Simple Test Email"
    msg["Message-ID"] = "<simple-test-123@example.com>"
    msg["Date"] = email.utils.formatdate()
    return msg


@pytest.fixture
def test_email_message_with_attachment():
    """Create a test email message with an attachment."""
    msg = MIMEMultipart()
    msg["From"] = "Test Sender <sender@example.com>"
    msg["To"] = "Test Recipient <recipient@example.com>"
    msg["Subject"] = "Email with Attachment"
    msg["Message-ID"] = "<attachment-test-123@example.com>"
    msg["Date"] = email.utils.formatdate()

    # Add text part
    text_part = MIMEText("This email has an attachment.", "plain")
    msg.attach(text_part)

    # Add attachment
    attachment = MIMEApplication(b"This is attachment content")
    attachment.add_header("Content-Disposition", "attachment", filename="test.txt")
    msg.attach(attachment)

    return msg


@contextmanager
def timed_operation(description: str) -> Generator[None, None, None]:
    """Context manager to measure and log operation time."""
    logger.info(f"Starting: {description}")
    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.info(f"Completed: {description} in {elapsed:.2f} seconds")
