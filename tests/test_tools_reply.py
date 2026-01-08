"""Tests for reply-related MCP tools."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context

from imap_mcp.models import Email, EmailAddress, EmailContent
from imap_mcp.tools import register_tools


class TestToolsReply:
    """Test class for reply-related MCP tools."""

    @pytest.fixture
    def mock_email(self):
        """Create a mock email object for testing."""
        email = Email(
            message_id="<test123@example.com>",
            subject="Test Email",
            from_=EmailAddress(name="Sender", address="sender@example.com"),
            to=[EmailAddress(name="Recipient", address="recipient@example.com")],
            cc=[],
            date=datetime.now(),
            content=EmailContent(text="Test content", html="<p>Test content</p>"),
            attachments=[],
            flags=["\\Seen"],
            headers={},
            folder="INBOX",
            uid=1,
        )
        return email

    @pytest.fixture
    def tools(self):
        """Set up tools for testing."""
        # Create a mock MCP server
        mcp = MagicMock(spec=FastMCP)

        # Make tool decorator store and return the decorated function
        stored_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                stored_tools[func.__name__] = func
                return func

            return decorator

        mcp.tool = mock_tool_decorator

        # Create mock clients
        imap_client = MagicMock()
        smtp_client = MagicMock()

        # Register tools with our mocks
        with patch("imap_mcp.tools.get_client_from_context") as mock_get_client:
            mock_get_client.return_value = imap_client
            with patch("imap_mcp.tools.get_smtp_client_from_context") as mock_get_smtp:
                mock_get_smtp.return_value = smtp_client
                register_tools(mcp, imap_client)

        # Return the tools dictionary and mocked clients
        return stored_tools, imap_client, smtp_client

    @pytest.fixture
    def mock_context(self):
        """Create a mock context for testing."""
        context = MagicMock(spec=Context)
        return context

    @pytest.mark.asyncio
    async def test_draft_reply_tool_success(self, tools, mock_email, mock_context):
        """Test successful creation of a draft reply."""
        tools_dict, imap_client, smtp_client = tools

        # Get the create_draft_reply function
        create_draft_reply = tools_dict["create_draft_reply"]

        # Mock successful email fetching
        with patch("imap_mcp.tools.get_client_from_context") as mock_get_client:
            mock_get_client.return_value = imap_client
            imap_client.fetch_email.return_value = mock_email
            imap_client.config.username = "me@example.com"

            # Mock successful MIME message creation and draft saving
            with patch("imap_mcp.smtp_client.create_reply_mime") as mock_create_reply:
                # Set up mock for create_reply_mime
                mime_message = MagicMock()
                mock_create_reply.return_value = mime_message

                # Set up mock for save_draft_mime
                draft_uid = 123
                imap_client.save_draft_mime.return_value = draft_uid
                imap_client._get_drafts_folder.return_value = "[Gmail]/Drafts"

                # Call the tool
                result_dict = await create_draft_reply(
                    folder="INBOX",
                    uid=1,
                    reply_body="This is my reply",
                    ctx=mock_context,
                )

                # Verify successful result
                assert result_dict["status"] == "success"
                assert result_dict["draft_uid"] == draft_uid

                # Verify correct method calls
                imap_client.fetch_email.assert_called_once_with(1, "INBOX")
                mock_create_reply.assert_called_once()
                imap_client.save_draft_mime.assert_called_once_with(mime_message)

    @pytest.mark.asyncio
    async def test_draft_reply_tool_with_options(self, tools, mock_email, mock_context):
        """Test draft reply with reply_all and cc options."""
        tools_dict, imap_client, smtp_client = tools

        # Get the create_draft_reply function
        create_draft_reply = tools_dict["create_draft_reply"]

        # Mock successful email fetching
        with patch("imap_mcp.tools.get_client_from_context") as mock_get_client:
            mock_get_client.return_value = imap_client
            imap_client.fetch_email.return_value = mock_email
            imap_client.config.username = "me@example.com"

            # Mock successful MIME message creation and draft saving
            with patch("imap_mcp.smtp_client.create_reply_mime") as mock_create_reply:
                # Set up mocks
                mime_message = MagicMock()
                mock_create_reply.return_value = mime_message
                draft_uid = 456
                imap_client.save_draft_mime.return_value = draft_uid
                imap_client._get_drafts_folder.return_value = "[Gmail]/Drafts"

                # Call the tool with reply_all and cc
                cc_list = ["extra@example.com", "another@example.com"]
                result_dict = await create_draft_reply(
                    folder="INBOX",
                    uid=1,
                    reply_body="Reply with options",
                    reply_all=True,
                    cc=cc_list,
                    ctx=mock_context,
                )

                # Verify successful result
                assert result_dict["status"] == "success"

                # Verify correct method calls with options
                mock_create_reply.assert_called_once()
                args, kwargs = mock_create_reply.call_args
                assert kwargs["reply_all"] is True
                assert len(kwargs["cc"]) == 2

    @pytest.mark.asyncio
    async def test_draft_reply_tool_fetch_fail(self, tools, mock_context):
        """Test handling when email fetch fails."""
        tools_dict, imap_client, smtp_client = tools

        # Get the create_draft_reply function
        create_draft_reply = tools_dict["create_draft_reply"]

        # Mock failed email fetching
        with patch("imap_mcp.tools.get_client_from_context") as mock_get_client:
            mock_get_client.return_value = imap_client
            imap_client.fetch_email.return_value = None

            # Call the tool
            result_dict = await create_draft_reply(
                folder="INBOX",
                uid=999,  # Non-existent UID
                reply_body="Reply to nothing",
                ctx=mock_context,
            )

            # Verify error result
            assert result_dict["status"] == "error"
            assert "not found" in result_dict["message"].lower()

            # Verify methods called correctly
            imap_client.fetch_email.assert_called_once()
            imap_client.save_draft_mime.assert_not_called()

    @pytest.mark.asyncio
    async def test_draft_reply_tool_save_fail(self, tools, mock_email, mock_context):
        """Test handling when draft saving fails."""
        tools_dict, imap_client, smtp_client = tools

        # Get the create_draft_reply function
        create_draft_reply = tools_dict["create_draft_reply"]

        # Mock successful email fetching but failed draft saving
        with patch("imap_mcp.tools.get_client_from_context") as mock_get_client:
            mock_get_client.return_value = imap_client
            imap_client.fetch_email.return_value = mock_email
            imap_client.config.username = "me@example.com"

            # Mock successful MIME message creation but failed draft saving
            with patch("imap_mcp.smtp_client.create_reply_mime") as mock_create_reply:
                # Set up mocks
                mime_message = MagicMock()
                mock_create_reply.return_value = mime_message
                imap_client.save_draft_mime.return_value = None  # Failed to save

                # Call the tool
                result_dict = await create_draft_reply(
                    folder="INBOX",
                    uid=1,
                    reply_body="Reply that can't be saved",
                    ctx=mock_context,
                )

                # Verify error result
                assert result_dict["status"] == "error"
                assert "failed to save" in result_dict["message"].lower()

                # Verify all methods were called
                imap_client.fetch_email.assert_called_once()
                mock_create_reply.assert_called_once()
                imap_client.save_draft_mime.assert_called_once()
