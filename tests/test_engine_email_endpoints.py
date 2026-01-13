import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from workspace_secretary.engine.api import app, state


@pytest.fixture(autouse=True)
def reset_state():
    state.enrolled = True
    state.config = MagicMock()
    state.config.imap.username = "me@example.com"
    state.config.imap.oauth2 = MagicMock()
    state.database = MagicMock()
    state.imap_client = MagicMock()
    yield
    state.imap_client = None


def _client():
    return TestClient(app)


def test_send_email_rejects_missing_config():
    state.config = None
    response = _client().post(
        "/api/email/send",
        json={"to": ["a@example.com"], "subject": "s", "body": "b"},
    )
    assert response.json()["status"] == "error"


def test_send_email_calls_smtp():
    with patch("workspace_secretary.engine.api.SMTPClient") as mock_smtp:
        mock_client = MagicMock()
        mock_smtp.return_value = mock_client
        response = _client().post(
            "/api/email/send",
            json={"to": ["a@example.com"], "subject": "s", "body": "b"},
        )
    assert response.json()["status"] == "ok"
    mock_client.send_message.assert_called_once()


def test_create_draft_reply_not_found():
    state.database.get_email_by_uid.return_value = None
    response = _client().post(
        "/api/email/draft-reply",
        json={"uid": 1, "folder": "INBOX", "body": "hi"},
    )
    assert response.json()["status"] == "error"


def test_create_draft_reply_success():
    state.database.get_email_by_uid.return_value = {
        "from_addr": "sender@example.com",
        "subject": "Hello",
        "message_id": "<mid>",
    }
    state.imap_client.save_draft_mime.return_value = 555

    response = _client().post(
        "/api/email/draft-reply",
        json={"uid": 1, "folder": "INBOX", "body": "Thanks"},
    )

    body = response.json()
    assert body["status"] == "ok"
    assert body["draft_uid"] == 555
    state.imap_client.save_draft_mime.assert_called_once()


def test_setup_labels_dry_run():
    state.imap_client.list_folders.return_value = []
    response = _client().post(
        "/api/email/setup-labels",
        json={"dry_run": True},
    )
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["created"]


def test_setup_labels_creates_missing():
    state.imap_client.list_folders.return_value = ["Secretary"]
    state.imap_client.create_folder.return_value = True

    response = _client().post(
        "/api/email/setup-labels",
        json={"dry_run": False},
    )

    payload = response.json()
    assert payload["status"] == "ok"
    assert "failed" in payload
    state.imap_client.create_folder.assert_called()
