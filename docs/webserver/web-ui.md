<!-- Refactored docs generated 2026-01-13 -->

# Google MailPilot Web Portal Overview

The FastAPI + HTMX portal complements the MCP tool layer with calendar-focused views, availability helpers, and the new booking link experience.

## Home / Calendar dashboard (`/calendar`)

The `/calendar` view is the primary human dashboard. It renders:
- **Day/week/month/agenda tabs** that pull events from the engine via `workspace_secretary.web.routes.calendar`.
- **Calendar selection state** showing which synced calendars are active, last sync timestamps, and synchronization health for each calendar.
- **Busy slots** derived from `/api/calendar/find-time` and the engine’s freebusy query, displayed as overlays on the grid.
- **Availability widget partial** (`/calendar/availability`) that can be embedded in other pages or shared with booking flows.

## Rescheduling & availability helpers

- `/calendar/find-time` renders an HTMX form that hits `/api/calendar/find-time` to surface spare slots between 11:00–22:00.
- `/api/calendar/propose-times` accepts JSON bundles of times+messages for proposing alternatives without mutating calendars.
- `/calendar/availability` exposes a embeddable widget for showing busy windows across the next `n` days.
- `/api/calendar/event/{calendar_id}/{event_id}` returns the event details for quick modal displays.

## Creating & responding to events

- `/api/calendar/event` accepts forms (summary, start/end, attendees, add_meet flag) and proxies to `engine.create_calendar_event`.
- `/calendar/api/create-event` is a simplified form for custom date/time inputs.
- `/api/calendar/respond/{event_id}` updates RSVP status (`accepted`, `declined`, `tentative`) respecting working hours and engine state.

## Booking links & public scheduling

MailPilot now hosts booking links downstream of `workspace_secretary/db/queries/booking_links.py`:
- `/book/{link_id}` renders the public HTML booking page (configured by host_name, description, duration).
- `/api/calendar/booking-slots` returns availability (with duration, busy windows, timezone awareness) for the requested link.
- `/api/calendar/book` accepts attendee info + a slot, creates the event via Engine API with `add_meet=True`, and acknowledges success.

## Linking to the MCP toolset

- The portal reuses the same Postgres database as the MCP server, so calendar events surfaced here match what tools like `get_daily_briefing` and `create_calendar_event` see.
- Booking links also rely on the new `booking_links` table, so toggling a link's `is_active` flag instantly updates the public page.

Next: [API endpoints](api.md) · [Configuration](configuration.md) · [MCP tools reference](../tools/index.md)
