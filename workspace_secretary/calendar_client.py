"""Google Calendar client for the AI Secretary."""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from workspace_secretary.config import ServerConfig

logger = logging.getLogger(__name__)


class CalendarClient:
    """Client for interacting with Google Calendar API."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.service = None
        self._creds = None

    def _get_credentials(self) -> Optional[Credentials]:
        """Convert our OAuth2Config to Google Credentials."""
        if not self.config.imap.oauth2:
            logger.error("OAuth2 configuration missing for Calendar")
            return None

        oauth = self.config.imap.oauth2
        creds = Credentials(
            token=oauth.access_token,
            refresh_token=oauth.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        )

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Note: In a real app, we'd want to save the new access_token back to config/file

        return creds

    def connect(self):
        """Initialize the Calendar service."""
        try:
            creds = self._get_credentials()
            if not creds:
                raise ValueError("Could not obtain credentials for Calendar")

            self.service = build("calendar", "v3", credentials=creds)
            logger.info("Successfully connected to Google Calendar API")
        except Exception as e:
            logger.error(f"Failed to connect to Google Calendar: {e}")
            raise

    def list_events(
        self, time_min: str, time_max: str, calendar_id: str = "primary"
    ) -> List[Dict[str, Any]]:
        """List events in a given time range."""
        if not self.service:
            self.connect()

        events_result = (
            self.service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        return events_result.get("items", [])

    def create_event(
        self, event_data: Dict[str, Any], calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Create a new calendar event."""
        if not self.service:
            self.connect()

        event = (
            self.service.events()
            .insert(calendarId=calendar_id, body=event_data)
            .execute()
        )

        logger.info(f"Created event: {event.get('htmlLink')}")
        return event

    def get_availability(self, time_min: str, time_max: str) -> Dict[str, Any]:
        """Check availability using the freebusy endpoint."""
        if not self.service:
            self.connect()

        body = {"timeMin": time_min, "timeMax": time_max, "items": [{"id": "primary"}]}

        return self.service.freebusy().query(body=body).execute()
