import pytest
import io
from unittest.mock import MagicMock, patch
from imap_mcp.models import Email, EmailAttachment, EmailContent, EmailAddress
from imap_mcp.tools import register_tools


@pytest.fixture
def get_attachment_tool():
    tools = {}

    class MockMCP:
        def tool(self, **kwargs):
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

    mcp = MockMCP()
    register_tools(mcp, MagicMock())
    return tools.get("get_attachment_content")


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    client = MagicMock()
    ctx.request_context.lifespan_context = {"imap_client": client}
    return ctx, client


@pytest.mark.asyncio
async def test_extract_text_from_txt_file(get_attachment_tool, mock_context):
    ctx, client = mock_context

    # Create mock email with text attachment
    att = EmailAttachment(
        filename="test.txt", content_type="text/plain", size=10, content=b"Hello World"
    )
    email_obj = MagicMock(spec=Email)
    email_obj.attachments = [att]
    client.fetch_email.return_value = email_obj

    result = await get_attachment_tool(
        folder="INBOX", uid=1, filename="test.txt", ctx=ctx
    )
    assert result == "Hello World"


@pytest.mark.asyncio
async def test_extract_text_from_pdf_mock(get_attachment_tool, mock_context):
    ctx, client = mock_context

    # Create mock email with PDF
    att = EmailAttachment(
        filename="test.pdf",
        content_type="application/pdf",
        size=10,
        content=b"%PDF-1.4 mock content",
    )
    email_obj = MagicMock(spec=Email)
    email_obj.attachments = [att]
    client.fetch_email.return_value = email_obj

    # Mock pypdf
    with patch("pypdf.PdfReader") as MockReader:
        mock_reader = MockReader.return_value
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Extracted PDF Text"
        mock_reader.pages = [mock_page]

        result = await get_attachment_tool(
            folder="INBOX", uid=1, filename="test.pdf", ctx=ctx
        )
        assert result == "Extracted PDF Text"


@pytest.mark.asyncio
async def test_attachment_not_found(get_attachment_tool, mock_context):
    ctx, client = mock_context
    email_obj = MagicMock(spec=Email)
    email_obj.attachments = []
    client.fetch_email.return_value = email_obj

    result = await get_attachment_tool(
        folder="INBOX", uid=1, filename="missing.txt", ctx=ctx
    )
    assert "Error: Attachment 'missing.txt' not found" in result
