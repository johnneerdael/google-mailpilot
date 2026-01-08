import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime
from imap_mcp.imap_client import ImapClient
from imap_mcp.tools import register_tools


@pytest.fixture
def mock_imap_client():
    client = MagicMock(spec=ImapClient)
    # Mock search results
    client.search.return_value = [1, 2, 3]
    # Mock fetch_emails results
    mock_email = MagicMock()
    mock_email.uid = 1
    mock_email.from_ = "sender@example.com"
    mock_email.subject = "Test Subject"
    mock_email.date = datetime(2024, 1, 1)
    mock_email.flags = ["\\Seen"]
    client.fetch_emails.return_value = {1: mock_email}
    return client


@pytest.fixture
def context(mock_imap_client):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"imap_client": mock_imap_client}
    return ctx


@pytest.fixture
def search_tool():
    tools = {}

    class MockMCP:
        def tool(self, **kwargs):
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

    mcp = MockMCP()
    register_tools(mcp, MagicMock())
    return tools.get("search_emails")


@pytest.mark.asyncio
async def test_advanced_search_and_logic(search_tool, mock_imap_client, context):
    """Test that dictionary criteria are correctly mapped to AND-style IMAP search list."""
    criteria = {
        "from": "boss@company.com",
        "since": "2024-01-01",
        "unread": True,
        "subject": "Urgent",
    }

    await search_tool(criteria=criteria, folder="INBOX", ctx=context)

    # Note: In our current implementation, we are mocking the search_tool to call
    # imap_client.search with the dictionary directly, because ImapClient.search
    # handles the conversion.
    # We need to verify that ImapClient.search would produce the right list.
    # Since we're mocking ImapClient, we can only verify it received the dict.
    args, kwargs = mock_imap_client.search.call_args
    assert args[0] == criteria


@pytest.mark.asyncio
async def test_advanced_search_mapping_logic():
    """Test that ImapClient.search correctly maps dictionary to IMAP list."""
    from imap_mcp.config import ImapConfig

    config = ImapConfig(
        host="imap.gmail.com", port=993, username="test@gmail.com", password="password"
    )
    client = ImapClient(config)

    # Mock the internal client to avoid connection
    client.client = MagicMock()
    client.connected = True

    criteria = {
        "from": "boss@company.com",
        "since": "2024-01-01",
        "unread": True,
        "subject": "Urgent",
    }

    with patch.object(client, "select_folder"):
        client.search(criteria, folder="INBOX")

        args, kwargs = client.client.search.call_args
        search_list = args[0]

        assert "FROM" in search_list
        assert "boss@company.com" in search_list
        assert "SINCE" in search_list
        # Note: SINCE value in ImapClient.search is converted to date object
        from datetime import date

        assert date(2024, 1, 1) in search_list
        assert "UNSEEN" in search_list
        assert "SUBJECT" in search_list
        assert "Urgent" in search_list


@pytest.mark.asyncio
async def test_wildcard_identity_search(search_tool, mock_imap_client, context):
    """Test searching with wildcard-style domain strings."""
    criteria = {"from": "@important.org"}

    await search_tool(criteria=criteria, folder="INBOX", ctx=context)

    args, kwargs = mock_imap_client.search.call_args
    assert args[0] == criteria
