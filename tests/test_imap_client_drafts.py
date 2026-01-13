import pytest
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from workspace_secretary.engine.imap_sync import ImapClient


def _build_message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Draft"
    message.set_content("body")
    return message


def test_save_draft_mime_returns_uid(mock_imap_config):
    client = ImapClient(mock_imap_config)
    mock_imap = MagicMock()
    mock_imap.append.return_value = b"[APPENDUID 12345 67890]"

    with (
        patch.object(client, "_get_client", return_value=mock_imap),
        patch.object(client, "_get_drafts_folder", return_value="[Gmail]/Drafts"),
    ):
        uid = client.save_draft_mime(_build_message())

    assert uid == 67890
    mock_imap.append.assert_called_once()
    called_args = mock_imap.append.call_args[0]
    assert called_args[0] == "[Gmail]/Drafts"
    assert called_args[2] == (r"\\Draft",)


def test_save_draft_mime_without_appenduid(mock_imap_config):
    client = ImapClient(mock_imap_config)
    mock_imap = MagicMock()
    mock_imap.append.return_value = b"OK"

    with (
        patch.object(client, "_get_client", return_value=mock_imap),
        patch.object(client, "_get_drafts_folder", return_value="Drafts"),
    ):
        uid = client.save_draft_mime(_build_message())

    assert uid is None


def test_save_draft_mime_handles_exception(mock_imap_config):
    client = ImapClient(mock_imap_config)
    mock_imap = MagicMock()
    mock_imap.append.side_effect = RuntimeError("append failed")

    with (
        patch.object(client, "_get_client", return_value=mock_imap),
        patch.object(client, "_get_drafts_folder", return_value="Drafts"),
    ):
        uid = client.save_draft_mime(_build_message())

    assert uid is None
