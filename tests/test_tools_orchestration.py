"""Tests for the meeting invite orchestration tool."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
from email.message import EmailMessage

from mcp.server.fastmcp import Context

from workspace_secretary.models import Email, EmailAddress, EmailContent
from workspace_secretary.imap_client import ImapClient
from workspace_secretary.config import ImapConfig
from workspace_secretary.tools import register_tools


class TestMeetingInviteOrchestration:
    """Tests for the meeting invite orchestration functionality."""

    @pytest.fixture
    def mock_context(self, mock_imap_client):
        """Create a mock MCP context."""
        ctx = MagicMock(spec=Context)
        ctx.kwargs = {"client": mock_imap_client}
        return ctx

    @pytest.fixture
    def mock_imap_client(self):
        """Create a mock IMAP client."""
        config = ImapConfig(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="password",
            use_ssl=True,
        )
        # We need a real-ish object for some attribute access, but mock the methods
        client = ImapClient(config)
        client.fetch_email = MagicMock(return_value=None)
        client.save_draft_mime = MagicMock(return_value=None)
        client._get_drafts_folder = MagicMock(return_value="Drafts")
        client.move_email = MagicMock(return_value=True)
        client.mark_email = MagicMock(return_value=True)
        client.delete_email = MagicMock(return_value=True)
        return client

    @pytest.fixture
    def mock_invite_email(self):
        """Create a mock meeting invite email."""
        return Email(
            message_id="<invite123@example.com>",
            subject="Meeting Invitation: Team Sync",
            from_=EmailAddress(name="Organizer", address="organizer@example.com"),
            to=[EmailAddress(name="Me", address="me@example.com")],
            date=datetime(2025, 4, 1, 10, 0, 0),
            content=EmailContent(
                text="You are invited to a team sync meeting.\nWhen: Tuesday, April 1, 2025 10:00 AM - 11:00 AM"
            ),
            headers={"Content-Type": "text/calendar; method=REQUEST"},
        )

    @pytest.fixture
    def mock_non_invite_email(self):
        """Create a mock non-invite email."""
        return Email(
            message_id="<message123@example.com>",
            subject="Regular Email",
            from_=EmailAddress(name="Sender", address="sender@example.com"),
            to=[EmailAddress(name="Me", address="me@example.com")],
            date=datetime(2025, 4, 1, 9, 0, 0),
            content=EmailContent(text="This is a regular email, not a meeting invite."),
            headers={},
        )

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP server."""
        mcp = MagicMock()
        tools = {}

        def tool_decorator(name=None):
            def wrapper(func):
                tools[name or func.__name__] = func
                return func

            return wrapper

        mcp.tool.side_effect = tool_decorator
        mcp._tools = tools
        return mcp

    @patch("workspace_secretary.workflows.invite_parser.identify_meeting_invite_details")
    @patch("workspace_secretary.workflows.calendar_mock.check_mock_availability")
    @patch("workspace_secretary.workflows.meeting_reply.generate_meeting_reply_content")
    @patch("workspace_secretary.smtp_client.create_reply_mime")
    @pytest.mark.asyncio
    async def test_process_meeting_invite_success(
        self,
        mock_create_reply_mime,
        mock_generate_reply,
        mock_check_availability,
        mock_identify_invite,
        mock_context,
        mock_imap_client,
        mock_invite_email,
        mock_mcp,
    ):
        """Test successful processing of a meeting invite."""
        # Setup mocks
        mock_imap_client.fetch_email.return_value = mock_invite_email

        # Mock invite identification
        mock_identify_invite.return_value = {
            "is_invite": True,
            "details": {
                "subject": "Team Sync",
                "start_time": datetime(2025, 4, 1, 10, 0, 0),
                "end_time": datetime(2025, 4, 1, 11, 0, 0),
                "organizer": "Organizer <organizer@example.com>",
                "location": "Conference Room",
            },
        }

        # Mock availability check
        mock_check_availability.return_value = {
            "available": True,
            "reason": "Time slot is available",
            "alternative_times": [],
        }

        # Mock reply generation
        mock_generate_reply.return_value = {
            "reply_subject": "Accepted: Team Sync",
            "reply_body": "I'll attend the meeting...",
            "reply_type": "accept",
        }

        # Mock MIME message creation
        mock_mime_message = MagicMock(spec=EmailMessage)
        mock_create_reply_mime.return_value = mock_mime_message

        # Mock draft saving
        mock_imap_client.save_draft_mime.return_value = 123

        # Register tools
        register_tools(mock_mcp, mock_imap_client)
        process_meeting_invite = mock_mcp._tools["process_meeting_invite"]

        # Call the function
        result = await process_meeting_invite(
            folder="INBOX",
            uid=456,
            ctx=mock_context,
            availability_mode="always_available",
        )

        # Assertions
        assert result["status"] == "success"
        assert result["draft_uid"] == 123
        assert result["draft_folder"] == "Drafts"
        assert result["availability"] is True

        # Verify the mock calls
        mock_imap_client.fetch_email.assert_called_once_with(456, "INBOX")
        mock_identify_invite.assert_called_once_with(mock_invite_email)

    @patch("workspace_secretary.workflows.invite_parser.identify_meeting_invite_details")
    @pytest.mark.asyncio
    async def test_process_non_invite_email(
        self,
        mock_identify_invite,
        mock_context,
        mock_imap_client,
        mock_non_invite_email,
        mock_mcp,
    ):
        """Test processing a non-invite email."""
        # Setup mocks
        mock_imap_client.fetch_email.return_value = mock_non_invite_email

        # Mock invite identification
        mock_identify_invite.return_value = {"is_invite": False, "details": {}}

        # Register tools
        register_tools(mock_mcp, mock_imap_client)
        process_meeting_invite = mock_mcp._tools["process_meeting_invite"]

        # Call the function
        result = await process_meeting_invite(folder="INBOX", uid=456, ctx=mock_context)

        # Assertions
        assert result["status"] == "not_invite"
        assert "The email is not a meeting invite" in result["message"]

        # Verify the mock calls
        mock_imap_client.fetch_email.assert_called_once_with(456, "INBOX")
        mock_identify_invite.assert_called_once_with(mock_non_invite_email)

    @pytest.mark.asyncio
    async def test_process_meeting_invite_email_not_found(
        self, mock_context, mock_imap_client, mock_mcp
    ):
        """Test handling when the email is not found."""
        # Setup mocks
        mock_imap_client.fetch_email.return_value = None

        # Register tools
        register_tools(mock_mcp, mock_imap_client)
        process_meeting_invite = mock_mcp._tools["process_meeting_invite"]

        # Call the function
        result = await process_meeting_invite(folder="INBOX", uid=456, ctx=mock_context)

        # Assertions
        assert result["status"] == "error"
        assert "not found" in result["message"]

        # Verify the mock calls
        mock_imap_client.fetch_email.assert_called_once_with(456, "INBOX")

    @patch("workspace_secretary.workflows.invite_parser.identify_meeting_invite_details")
    @patch("workspace_secretary.workflows.calendar_mock.check_mock_availability")
    @patch("workspace_secretary.workflows.meeting_reply.generate_meeting_reply_content")
    @patch("workspace_secretary.smtp_client.create_reply_mime")
    @pytest.mark.asyncio
    async def test_process_meeting_invite_save_draft_failure(
        self,
        mock_create_reply_mime,
        mock_generate_reply,
        mock_check_availability,
        mock_identify_invite,
        mock_context,
        mock_imap_client,
        mock_invite_email,
        mock_mcp,
    ):
        """Test handling when saving the draft fails."""
        # Setup mocks
        mock_imap_client.fetch_email.return_value = mock_invite_email

        # Mock invite identification
        mock_identify_invite.return_value = {
            "is_invite": True,
            "details": {
                "subject": "Team Sync",
                "start_time": datetime(2025, 4, 1, 10, 0, 0),
                "end_time": datetime(2025, 4, 1, 11, 0, 0),
                "organizer": "Organizer <organizer@example.com>",
                "location": "Conference Room",
            },
        }

        # Mock availability check
        mock_check_availability.return_value = {
            "available": False,
            "reason": "Calendar is busy during this time",
            "alternative_times": [],
        }

        # Mock reply generation
        mock_generate_reply.return_value = {
            "reply_subject": "Declined: Team Sync",
            "reply_body": "I'm unable to attend the meeting...",
            "reply_type": "decline",
        }

        # Mock MIME message creation
        mock_mime_message = MagicMock(spec=EmailMessage)
        mock_create_reply_mime.return_value = mock_mime_message

        # Mock draft saving failure
        mock_imap_client.save_draft_mime.return_value = None

        # Register tools
        register_tools(mock_mcp, mock_imap_client)
        process_meeting_invite = mock_mcp._tools["process_meeting_invite"]

        # Call the function
        result = await process_meeting_invite(
            folder="INBOX", uid=456, ctx=mock_context, availability_mode="always_busy"
        )

        # Assertions
        assert result["status"] == "error"
        assert "Failed to save draft" in result["message"]
        assert result["availability"] is False

        # Verify the mock calls
        mock_imap_client.fetch_email.assert_called_once_with(456, "INBOX")
