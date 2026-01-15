<!-- Refactored docs generated 2026-01-13 -->

# Web Portal API reference

All JSON endpoints live under FastAPI (via `workspace_secretary.web.routes.calendar` and related routers) and require the same session cookie/CSRF protections described in the security guide.

## Key HTML endpoints

| Route | Description |
|-------|-------------|
| `/calendar` | Main calendar dashboard (day/week/month/agenda) with sync state and busy overlays |
| `/calendar/find-time` | HTMX form to pick spare blocks (proxies to `/api/calendar/find-time`) |
| `/calendar/availability` | Embedded widget showing your busy slots for the next `n` days |
| `/book/{link_id}` | Public booking page for shared scheduling links |

## JSON & POST endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/calendar/find-time` | POST | Returns available slots between 11:00–22:00 within a date range (duration, timezone, attendees) |
| `/api/calendar/propose-times` | POST | Accepts JSON-proposed times & messages for use in UI workflows (no mutation) |
| `/api/calendar/event/{calendar_id}/{event_id}` | GET | Fetch calendar event details for modals / quick views |
| `/api/calendar/event` | POST | Creates an event via the engine (summary, attendees, add_meet flag) |
| `/calendar/api/create-event` | POST | Simplified create form using separate date/time fields |
| `/api/calendar/respond/{event_id}` | POST | Responds to an invite (`accepted`, `declined`, `tentative`) respecting working hours |
| `/api/calendar/booking-slots` | GET | Returns availability for a booking link (uses `booking_links` metadata) |
| `/api/calendar/book` | POST | Books a slot for a booking link — creates the event with `add_meet=True` and records attendees |

## Embeddable partials & helpers

| Endpoint | Description |
|----------|-------------|
| `/calendar/availability` | Returns the partial template `partials/availability_widget.html` for busy windows (days parameter supported) |

## Session requirements

- Every endpoint expects either: a valid session cookie or an `X-Requested-With: XMLHttpRequest` header along with CSRF tokens for POSTs.
- Booking endpoints (`/book/{link_id}`, `/api/calendar/booking-slots`, `/api/calendar/book`) are public but validate `link_id` + `is_active` before acting.
