import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime
from mcp.server.fastmcp import FastMCP, Context
from workspace_secretary.tools import register_tools
from workspace_secretary.models import EmailAddress


@pytest.fixture
def mock_gmail_client():
    client = MagicMock()
    # Mock search results for unread invites
    client.search_messages.return_value = [
        {"id": "invite_123", "threadId": "thread_invite"}
    ]

    # Mock the invite email
    mock_email = MagicMock()
    mock_email.message_id = "invite_123"
    mock_email.gmail_thread_id = "thread_invite"
    mock_email.subject = "Meeting: Project Sync"
    mock_email.from_ = EmailAddress(name="Boss", address="boss@company.com")
    mock_email.content.get_best_content.return_value = (
        "Let's meet tomorrow at 10am to discuss the project."
    )
    mock_email.date = datetime(2024, 1, 1)
    mock_email.gmail_labels = ["INBOX"]

    client.get_message.return_value = mock_email
    client.fetch_email.return_value = mock_email
    return client


@pytest.fixture
def mock_calendar_client():
    client = MagicMock()
    # Mock availability (free)
    client.get_availability.return_value = {"calendars": {"primary": {"busy": []}}}
    return client


@pytest.fixture
def context(mock_gmail_client, mock_calendar_client):
    ctx = MagicMock(spec=Context)
    ctx.request_context.lifespan_context = {
        "gmail_client": mock_gmail_client,
        "calendar_client": mock_calendar_client,
        "imap_client": mock_gmail_client,  # Fallback
    }
    return ctx


@pytest.fixture
def tools():
    mcp = MagicMock(spec=FastMCP)
    registered_tools = {}

    def tool_decorator(**kwargs):
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool.side_effect = tool_decorator
    register_tools(mcp, MagicMock())
    return registered_tools


@pytest.mark.asyncio
async def test_executive_triage_flow(
    tools, context, mock_gmail_client, mock_calendar_client
):
    """Test the full triage workflow: search -> check availability -> create reply."""

    # 1. Search for unread invites
    search_tool = tools["gmail_search"]
    search_results = await search_tool(query="is:unread Meeting", ctx=context)
    messages = json.loads(search_results)

    assert len(messages) == 1
    assert messages[0]["id"] == "invite_123"

    # 2. Check availability
    avail_tool = tools["get_calendar_availability"]
    # Mocking tomorrow's date
    avail_results = await avail_tool(
        time_min="2024-01-02T10:00:00Z", time_max="2024-01-02T11:00:00Z", ctx=context
    )
    availability = json.loads(avail_results)
    assert "calendars" in availability

    # 3. Create draft reply (using create_draft_reply tool)
    draft_tool = tools["create_draft_reply"]
    # We mock save_draft_mime in the client
    mock_gmail_client.save_draft_mime.return_value = 555
    mock_gmail_client._get_drafts_folder.return_value = "[Gmail]/Drafts"
    mock_gmail_client.config.username = "test@gmail.com"

    draft_result = await draft_tool(
        folder="INBOX",
        uid=123,  # This would be mapped from message ID in a real scenario
        reply_body="I've checked my calendar and I am free. Looking forward to it!",
        ctx=context,
    )

    assert draft_result["status"] == "success"
    assert draft_result["draft_uid"] == "555"
    mock_gmail_client.save_draft_mime.assert_called()
