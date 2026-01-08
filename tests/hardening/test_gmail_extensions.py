import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime
from workspace_secretary.imap_client import ImapClient
from workspace_secretary.models import Email, EmailAddress


@pytest.fixture
def mock_imap_client():
    client = MagicMock(spec=ImapClient)
    # Mock capabilities to include Gmail extensions
    client.get_capabilities.return_value = ["IMAP4rev1", "X-GM-EXT-1"]
    return client


def test_fetch_emails_with_gmail_extensions(mock_imap_client):
    """Test that fetch_emails correctly extracts Gmail thread ID and labels."""
    # This is a bit tricky because fetch_emails is what we want to test,
    # but we're mocking the ImapClient. Let's use a real ImapClient instance
    # but mock its internal imapclient.IMAPClient.

    from workspace_secretary.config import ImapConfig

    config = ImapConfig(
        host="imap.gmail.com", port=993, username="test@gmail.com", password="password"
    )
    client = ImapClient(config)

    # Mock the internal imapclient
    mock_internal_client = MagicMock()
    client.client = mock_internal_client
    client.connected = True

    # Mock capabilities
    mock_internal_client.capabilities.return_value = [b"IMAP4rev1", b"X-GM-EXT-1"]

    # Mock fetch response with Gmail extensions
    uid = 123
    mock_internal_client.fetch.return_value = {
        uid: {
            b"BODY.PEEK[]": b"Subject: Test\r\n\r\nContent",
            b"FLAGS": (b"\\Seen",),
            b"X-GM-THRID": b"123456789",
            b"X-GM-LABELS": (b"Label1", b"Label2"),
        }
    }

    emails = client.fetch_emails([uid], folder="INBOX")

    assert uid in emails
    email_obj = emails[uid]
    assert email_obj.gmail_thread_id == "123456789"
    assert "Label1" in email_obj.gmail_labels
    assert "Label2" in email_obj.gmail_labels
    assert "\\Seen" in email_obj.flags


def test_fetch_thread_with_gmail_optimization():
    """Test that fetch_thread uses X-GM-THRID when available."""
    from workspace_secretary.config import ImapConfig

    config = ImapConfig(
        host="imap.gmail.com", port=993, username="test@gmail.com", password="password"
    )
    client = ImapClient(config)

    # Mock internal methods
    initial_email = MagicMock(spec=Email)
    initial_email.uid = 100
    initial_email.gmail_thread_id = "thread123"
    initial_email.subject = "Test Subject"
    initial_email.headers = {"Message-ID": "<msg1@example.com>"}

    with (
        patch.object(client, "fetch_email", return_value=initial_email),
        patch.object(client, "get_capabilities", return_value=["X-GM-EXT-1"]),
        patch.object(client, "search_by_thread_id", return_value=[100, 101, 102]),
        patch.object(client, "fetch_emails") as mock_fetch_emails,
        patch.object(client, "select_folder"),
        patch.object(client, "ensure_connected"),
    ):
        # Mock fetch_emails to return the emails in the thread
        email100 = MagicMock(spec=Email)
        email100.uid = 100
        email100.date = datetime(2024, 1, 1)
        email101 = MagicMock(spec=Email)
        email101.uid = 101
        email101.date = datetime(2024, 1, 2)
        email102 = MagicMock(spec=Email)
        email102.uid = 102
        email102.date = datetime(2024, 1, 3)
        mock_fetch_emails.return_value = {100: email100, 101: email101, 102: email102}

        thread = client.fetch_thread(100, "INBOX")

        # Verify search_by_thread_id was called
        client.search_by_thread_id.assert_called_once_with("thread123", "INBOX")
        assert len(thread) == 3
        assert thread[0].uid == 100
        assert thread[1].uid == 101
        assert thread[2].uid == 102


def test_modify_gmail_labels():
    """Test adding/removing Gmail labels."""
    from workspace_secretary.config import ImapConfig

    config = ImapConfig(
        host="imap.gmail.com", port=993, username="test@gmail.com", password="password"
    )
    client = ImapClient(config)

    mock_internal_client = MagicMock()
    client.client = mock_internal_client
    client.connected = True

    with patch.object(client, "get_capabilities", return_value=["X-GM-EXT-1"]):
        # Test add
        client.add_gmail_labels(123, "INBOX", ["MyLabel"])
        mock_internal_client.add_gmail_labels.assert_called_once_with(
            [123], ["MyLabel"]
        )

        # Test remove
        client.remove_gmail_labels(123, "INBOX", ["OldLabel"])
        mock_internal_client.remove_gmail_labels.assert_called_once_with(
            [123], ["OldLabel"]
        )

        # Test set
        client.set_gmail_labels(123, "INBOX", ["NewLabel"])
        mock_internal_client.set_gmail_labels.assert_called_once_with(
            [123], ["NewLabel"]
        )
