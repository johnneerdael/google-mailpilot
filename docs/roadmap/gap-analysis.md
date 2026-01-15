# Priority gap analysis

## v5.0.0 completed work

- Tools and handlers now register immediately upon import, fixing FastMCP tool visibility issues for every MCP client.
- Batch tools (`triage_priority_emails`, `quick_clean_inbox`, `triage_remaining_emails`) handle `raw:` continuation states so FastMCP no longer converts JSON strings into dicts before validation.
- Synchronous end-to-end tests (`tests/test_triage_priority_emails.py`, `tests/test_web_compose.py`) cover the triage and compose experiences without relying on `pytest-asyncio`.
- Booking links (`/book/{link_id}`, `/api/calendar/booking-slots`, `/api/calendar/book`) launch with dedicated helpers in `workspace_secretary/db/queries/booking_links.py` plus new templates and routes.
- The shared Postgres + pgvector database schema powers semantic search tools and new email/security signals (SPF/DKIM/DMARC) exported by `workspace_secretary/email_auth.py`.

## Remaining tactical gaps

| Gap | Why it matters | Next step |
|-----|----------------|-----------|
| **Attachment uploads in compose** | Compose still cannot accept files, depriving workflows of proof-of-delivery | Add upload widget + graph API/SMTP bridging, reuse booking metadata pattern for attachments |
| **Calendar editing + delete UI** | Users can book slots but not update or cancel them from the web UI | Surface Engine APIs for edit/delete in `workspace_secretary/web/routes/calendar.py` and add confirm/modals in templates |
| **UX feedback loop (notifications, toasts)** | Actions lack persistent feedback, reducing trust even though mutations remain safe | Build toast/alert system integrated with `workspace_secretary/web/routes/dashboard.py` and the new booking template |
| **Keyboard navigation & power shortcuts** | The UI remains mouse-heavy, while the server emphasizes keyboard-first agent flows | Add `j/k` navigation, command palette, and visible shortcut help modal; align HTMX with tool signals |
| **Mobile/responsive experience** | Swipe/gesture support and mobile layout are still placeholder text | Rework templates for responsive breakpoints (`calendar.html`, `compose.html`, `dashboard.html`) and mobile-specific partials |

## Strategic (future) focus

1. **Contacts & autocomplete** — integrate contact/address book data into compose and triage contexts (signals already capture VIPs and `mentions_my_name`).
2. **Rules/filters UI** — let users configure automated labels and folder routing via the Secretary label set.
3. **Offline-assisted workflows** — extend the engine’s background sync to resume when the UI goes offline, exposing sync status/last sync metadata in the Web UI.
4. **Theme + accessibility polish** — deliver a toggleable theme, high-contrast styles, and HTMX-friendly focus states aligning with MailPilot’s AI-first promise.

