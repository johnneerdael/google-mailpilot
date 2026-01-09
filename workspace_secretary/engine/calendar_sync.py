"""Google Calendar client for the AI Secretary."""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from workspace_secretary.config import ServerConfig
from workspace_secretary.engine.oauth2 import get_access_token

logger = logging.getLogger(__name__)


class CalendarClient:
    """Client for interacting with Google Calendar API."""

    def __init__(self, config: ServerConfig):
        self.config: ServerConfig = config
        self.service: Any = None
        self._creds: Optional[Credentials] = None

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
            scopes=["https://www.googleapis.com/auth/calendar"],
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

    def _ensure_connected(self) -> Any:
        """Ensure service is connected and return it."""
        if not self.service:
            self.connect()
        if not self.service:
            raise RuntimeError("Failed to connect to Calendar service")
        return self.service

    def list_events(
        self, time_min: str, time_max: str, calendar_id: str = "primary"
    ) -> List[Dict[str, Any]]:
        """List events in a given time range."""
        service = self._ensure_connected()

        events_result = (
            service.events()
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
        self,
        event_data: Dict[str, Any],
        calendar_id: str = "primary",
        conference_data_version: int = 0,
    ) -> Dict[str, Any]:
        """Create a new calendar event.

        Args:
            event_data: Event details
            calendar_id: Calendar ID
            conference_data_version: Version for conference data (set to 1 to enable Meet)
        """
        service = self._ensure_connected()

        event = (
            service.events()
            .insert(
                calendarId=calendar_id,
                body=event_data,
                conferenceDataVersion=conference_data_version,
            )
            .execute()
        )

        logger.info(f"Created event: {event.get('htmlLink')}")
        return event

    def get_availability(self, time_min: str, time_max: str) -> Dict[str, Any]:
        """Check availability using the freebusy endpoint."""
        service = self._ensure_connected()

        body = {"timeMin": time_min, "timeMax": time_max, "items": [{"id": "primary"}]}

        return service.freebusy().query(body=body).execute()


class CalendarSync:
    def __init__(self, client: CalendarClient, cache: "CalendarCache"):
        self.client = client
        self.cache = cache

    def sync_calendar(self, calendar_id: str = "primary") -> dict[str, Any]:
        service = self.client._ensure_connected()

        sync_token = self.cache.get_sync_token(calendar_id)

        if sync_token:
            return self._incremental_sync(service, calendar_id, sync_token)
        else:
            return self._full_sync(service, calendar_id)

    def _full_sync(self, service: Any, calendar_id: str) -> dict[str, Any]:
        logger.info(f"Starting full calendar sync for {calendar_id}")

        self.cache.clear_calendar(calendar_id)

        try:
            cal_info = service.calendars().get(calendarId=calendar_id).execute()
            self.cache.upsert_calendar(
                calendar_id=calendar_id,
                summary=cal_info.get("summary", calendar_id),
                description=cal_info.get("description"),
                timezone=cal_info.get("timeZone"),
                access_role=cal_info.get("accessRole"),
            )
        except Exception as e:
            logger.warning(f"Could not fetch calendar info: {e}")

        total_events = 0
        page_token = None
        next_sync_token = None

        while True:
            events_result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    pageToken=page_token,
                    maxResults=250,
                    singleEvents=False,
                    showDeleted=False,
                )
                .execute()
            )

            for event in events_result.get("items", []):
                self.cache.upsert_event(event, calendar_id)
                total_events += 1

            page_token = events_result.get("nextPageToken")
            if not page_token:
                next_sync_token = events_result.get("nextSyncToken")
                break

        if next_sync_token:
            self.cache.update_sync_token(calendar_id, next_sync_token)

        logger.info(f"Full sync complete: {total_events} events synced")
        return {"status": "full_sync", "events_synced": total_events}

    def _incremental_sync(
        self, service: Any, calendar_id: str, sync_token: str
    ) -> dict[str, Any]:
        logger.info(f"Starting incremental calendar sync for {calendar_id}")

        added = 0
        updated = 0
        deleted = 0
        page_token = None
        next_sync_token = None

        try:
            while True:
                events_result = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        syncToken=sync_token,
                        pageToken=page_token,
                        maxResults=250,
                        showDeleted=True,
                    )
                    .execute()
                )

                for event in events_result.get("items", []):
                    event_id = event.get("id")
                    if not event_id:
                        continue

                    if event.get("status") == "cancelled":
                        self.cache.delete_event(event_id)
                        deleted += 1
                    else:
                        existing = self.cache.get_event(event_id)
                        self.cache.upsert_event(event, calendar_id)
                        if existing:
                            updated += 1
                        else:
                            added += 1

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    next_sync_token = events_result.get("nextSyncToken")
                    break

            if next_sync_token:
                self.cache.update_sync_token(calendar_id, next_sync_token)

            logger.info(f"Incremental sync: +{added} ~{updated} -{deleted}")
            return {
                "status": "incremental_sync",
                "added": added,
                "updated": updated,
                "deleted": deleted,
            }

        except Exception as e:
            if "Sync token" in str(e) or "410" in str(e):
                logger.warning("Sync token invalid, falling back to full sync")
                return self._full_sync(service, calendar_id)
            raise


if TYPE_CHECKING:
    from workspace_secretary.engine.calendar_cache import CalendarCache
