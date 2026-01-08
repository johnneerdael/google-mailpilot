import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime
from workspace_secretary.gmail_client import GmailClient
from workspace_secretary.models import EmailAddress
from mcp.server.fastmcp import FastMCP, Context


@pytest.fixture
def mock_gmail_client():
    client = MagicMock(spec=GmailClient)
    # Mock search results
    client.search_messages.return_value = [{"id": "msg123", "threadId": "thread123"}]

    # Mock get_message results
    mock_email = MagicMock()
    mock_email.message_id = "msg123"
    mock_email.gmail_thread_id = "thread123"
    mock_email.from_ = EmailAddress(name="Sender", address="sender@example.com")
    mock_email.subject = "Test Subject"
    mock_email.date = datetime(2024, 1, 1)
    mock_email.gmail_labels = ["INBOX", "UNREAD"]

    client.get_message.return_value = mock_email
    return client


@pytest.fixture
def context(mock_gmail_client):
    ctx = MagicMock(spec=Context)
    # Mock the lifespan context structure used by get_gmail_client_from_context
    ctx.request_context.lifespan_context = {"gmail_client": mock_gmail_client}
    return ctx


@pytest.fixture
def gmail_search_tool():
    # Tools are inner functions in register_tools, but we can access them
    # by mocking FastMCP and capturing the decorated functions
    tools = {}
    mcp = MagicMock(spec=FastMCP)

    def tool_decorator(**kwargs):
        def wrapper(func):
            tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool.side_effect = tool_decorator

    from workspace_secretary.tools import register_tools

    register_tools(mcp, MagicMock())

    return tools.get("gmail_search")


@pytest.mark.asyncio
async def test_gmail_search_syntax(gmail_search_tool, mock_gmail_client, context):
    """Test searching with Gmail's native query syntax."""
    query = "has:attachment from:boss"

    result_json = await gmail_search_tool(query=query, max_results=10, ctx=context)
    result = json.loads(result_json)

    # Verify client was called with correct query
    mock_gmail_client.search_messages.assert_called_with(query, 10)

    # Verify response structure
    assert len(result) == 1
    assert result[0]["id"] == "msg123"
    assert result[0]["subject"] == "Test Subject"


@pytest.mark.asyncio
async def test_gmail_search_empty_results(
    gmail_search_tool, mock_gmail_client, context
):
    """Test handling of no search results."""
    mock_gmail_client.search_messages.return_value = []

    result_json = await gmail_search_tool(query="nonexistent", ctx=context)
    result = json.loads(result_json)

    assert result == []
