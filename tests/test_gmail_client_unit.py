"""Unit tests for the Gmail REST API client."""

import pytest
from unittest.mock import MagicMock
from workspace_secretary.gmail_client import GmailClient
from workspace_secretary.config import ServerConfig


def test_parse_gmail_message_simple(mock_gmail_service):
    """Test parsing a simple Gmail API message response."""
    config = MagicMock(spec=ServerConfig)
    client = GmailClient(config)
    client.service = mock_gmail_service

    msg_raw = {
        "id": "12345",
        "threadId": "thread_abc",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hello world",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test Subject"},
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Fri, 1 Jan 2024 10:00:00 +0000"},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": "SGVsbG8gZnJvbSBHbWFpbCBSRVNUIEFQSQ=="
                    },  # "Hello from Gmail REST API"
                }
            ],
        },
    }

    email_obj = client._parse_gmail_message(msg_raw)

    assert email_obj.message_id == "12345"
    assert email_obj.gmail_thread_id == "thread_abc"
    assert "INBOX" in email_obj.gmail_labels
    assert email_obj.subject == "Test Subject"
    assert email_obj.from_.address == "sender@example.com"
    assert email_obj.content.text == "Hello from Gmail REST API"


def test_gmail_search_logic(mock_gmail_service):
    """Test the search tool logic using the mock service."""
    config = MagicMock(spec=ServerConfig)
    client = GmailClient(config)
    client.service = mock_gmail_service

    # Configure mock response for list
    mock_gmail_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}]
    }

    results = client.search_messages("from:netskope")

    assert len(results) == 2
    assert results[0]["id"] == "m1"
    mock_gmail_service.users().messages().list.assert_called_with(
        userId="me", q="from:netskope", maxResults=50
    )


def test_gmail_get_thread(mock_gmail_service):
    """Test fetching an entire conversation thread."""
    config = MagicMock(spec=ServerConfig)
    client = GmailClient(config)
    client.service = mock_gmail_service

    mock_gmail_service.users().threads().get().execute.return_value = {
        "id": "t1",
        "messages": [
            {
                "id": "m1",
                "payload": {"headers": [{"name": "Subject", "value": "Re: Test"}]},
            },
            {
                "id": "m2",
                "payload": {"headers": [{"name": "Subject", "value": "Re: Test"}]},
            },
        ],
    }

    thread = client.get_thread("t1")

    assert len(thread) == 2
    assert thread[0].message_id == "m1"
    assert thread[1].message_id == "m2"
