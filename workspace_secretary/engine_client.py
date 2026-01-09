import json
import logging
import os
import socket
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

SOCKET_PATH = os.environ.get("ENGINE_SOCKET", "/tmp/secretary-engine.sock")


class EngineClient:
    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            transport = httpx.HTTPTransport(uds=self.socket_path)
            self._client = httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=30.0,
            )
        return self._client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self._get_client()
        try:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot connect to engine at {self.socket_path}. "
                "Is secretary-engine running?"
            )
        except httpx.HTTPStatusError as e:
            error_detail = e.response.json().get("detail", str(e))
            raise RuntimeError(f"Engine error: {error_detail}")

    def get_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def trigger_sync(self) -> dict[str, Any]:
        return self._request("POST", "/api/sync/trigger")

    def move_email(self, uid: int, folder: str, destination: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/move",
            json={"uid": uid, "folder": folder, "destination": destination},
        )

    def mark_read(self, uid: int, folder: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/mark-read",
            json={"uid": uid, "folder": folder},
        )

    def mark_unread(self, uid: int, folder: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/mark-unread",
            json={"uid": uid, "folder": folder},
        )

    def modify_labels(
        self, uid: int, folder: str, labels: list[str], action: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/labels",
            json={"uid": uid, "folder": folder, "labels": labels, "action": action},
        )

    def create_calendar_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary",
        meeting_type: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/calendar/event",
            json={
                "summary": summary,
                "start_time": start_time,
                "end_time": end_time,
                "description": description,
                "location": location,
                "calendar_id": calendar_id,
                "meeting_type": meeting_type,
            },
        )

    def respond_to_meeting(
        self, event_id: str, calendar_id: str, response: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/calendar/respond",
            json={
                "event_id": event_id,
                "calendar_id": calendar_id,
                "response": response,
            },
        )

    def list_calendar_events(
        self, time_min: str, time_max: str, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/calendar/events",
            params={
                "time_min": time_min,
                "time_max": time_max,
                "calendar_id": calendar_id,
            },
        )

    def get_calendar_availability(self, time_min: str, time_max: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/calendar/availability",
            params={"time_min": time_min, "time_max": time_max},
        )

    def setup_labels(self, dry_run: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/setup-labels",
            json={"dry_run": dry_run},
        )

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/send",
            json={
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc,
            },
        )

    def create_draft_reply(
        self,
        uid: int,
        folder: str,
        body: str,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/email/draft-reply",
            json={
                "uid": uid,
                "folder": folder,
                "body": body,
                "reply_all": reply_all,
            },
        )


_engine_client: Optional[EngineClient] = None


def get_engine_client() -> EngineClient:
    global _engine_client
    if _engine_client is None:
        _engine_client = EngineClient()
    return _engine_client
