"""Unit tests for the Calendar API client."""

import pytest
from unittest.mock import MagicMock
from workspace_secretary.calendar_client import CalendarClient
from workspace_secretary.config import ServerConfig


def test_list_calendar_events(mock_calendar_service):
    """Test listing calendar events."""
    config = MagicMock(spec=ServerConfig)
    client = CalendarClient(config)
    client.service = mock_calendar_service

    mock_calendar_service.events().list().execute.return_value = {
        "items": [
            {
                "id": "evt1",
                "summary": "Meeting 1",
                "start": {"dateTime": "2024-01-01T10:00:00Z"},
                "end": {"dateTime": "2024-01-01T11:00:00Z"},
            }
        ]
    }

    events = client.list_events("2024-01-01T00:00:00Z", "2024-01-01T23:59:59Z")

    assert len(events) == 1
    assert events[0]["summary"] == "Meeting 1"
    mock_calendar_service.events().list.assert_called_with(
        calendarId="primary",
        timeMin="2024-01-01T00:00:00Z",
        timeMax="2024-01-01T23:59:59Z",
        singleEvents=True,
        orderBy="startTime",
    )


def test_create_calendar_event(mock_calendar_service):
    """Test creating a calendar event."""
    config = MagicMock(spec=ServerConfig)
    client = CalendarClient(config)
    client.service = mock_calendar_service

    event_data = {
        "summary": "New Meeting",
        "start": {"dateTime": "2024-01-02T10:00:00Z"},
        "end": {"dateTime": "2024-01-02T11:00:00Z"},
    }

    client.create_event(event_data)

    mock_calendar_service.events().insert.assert_called_with(
        calendarId="primary", body=event_data, conferenceDataVersion=0
    )


def test_get_calendar_availability(mock_calendar_service):
    """Test checking availability."""
    config = MagicMock(spec=ServerConfig)
    client = CalendarClient(config)
    client.service = mock_calendar_service

    mock_calendar_service.freebusy().query().execute.return_value = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2024-01-01T10:00:00Z", "end": "2024-01-01T11:00:00Z"}
                ]
            }
        }
    }

    availability = client.get_availability(
        "2024-01-01T00:00:00Z", "2024-01-01T23:59:59Z"
    )

    assert "primary" in availability["calendars"]
    assert len(availability["calendars"]["primary"]["busy"]) == 1
