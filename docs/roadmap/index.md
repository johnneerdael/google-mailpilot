# Google MailPilot Roadmap

**Release**: v5.0.0 (2026-01-15) — the brand-new public launch for the renamed MailPilot stack. This roadmap now centers on the production-ready MCP toolset, the shared Postgres/pgvector backend, and the public booking link experience.

## v5.0.0 deliverables

- **MailPilot rebrand**: all collateral, badges, repo links, and documentation now point to `johnneerdael/google-mailpilot` and the new doc site.
- **Tool registration fix**: `workspace_secretary.tools` registers at import time so FastMCP exposes every API immediately, eliminating late-registration bugs.
- **Continuation resilience**: `triage_priority_emails` and other batch tools honor `raw:`-prefixed `continuation_state` payloads so FastMCP no longer pre-parses JSON strings into dicts.
- **Synchronous triage + compose tests**: `tests/test_triage_priority_emails.py` and `tests/test_web_compose.py` now run under plain `pytest` (no `pytest-asyncio`) via `asyncio.run(tools.mcp.call_tool(...))`, matching the production MCP tooling.
- **Booking links**: new helpers (`workspace_secretary/db/queries/booking_links.py`) and routes (`/book/{link_id}`, `/api/calendar/booking-slots`, `/api/calendar/book`) let invitees reserve time slots without exposing Google credentials.
- **Email/auth intelligence**: `workspace_secretary/email_auth.py` extracts SPF/DKIM/DMARC signals for the phishing analyzer, while the Engine/Web routes now surface those signals in responses.
- **Postgres + pgvector-first**: The docs, configuration, and deployments now require Postgres (pgvector) for semantic search, replacing the old SQLite fallback.

## What’s next (2026 roadmap)

1. **Booking UX polish** — refine `calendar_booking.html`, add GDPR/branding text, and support multi-day availability windows.
2. **Signal-aware compose helpers** — integrate `email_auth` results into compose drafts (e.g., warn on failed SPF/DKIM) and boost `workspace_secretary/web/routes/compose.py` metadata.
3. **Tooling observability** — expose MCP health metrics (tool registration latency, continuation-state failures) via `/health` and `workspace_secretary/web/routes/health.py`.
4. **Advanced calendar features** — add editing controls (edit/delete), richer availability views (day/month), and calendar reminders still missing from the web UI.
5. **Desktop/mobile interactions** — meaningful mobile-friendly layouts, swipe actions, and keyboard shortcuts (`j/k`, command palette) once the static UI reaches feature parity.

## Read next

- [Codebase structure](./codebase-structure.md)
- [Priority gap analysis](./gap-analysis.md)
- [Recommendations & phases](./recommendations.md)
- [Appendix: feature coverage by route](./appendix-routes.md)
- [Getting Started](../getting-started.md)
- [MCP Tools Reference](../tools/index.md)
