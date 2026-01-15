# Platform-Level Operations for Google MailPilot

This guide dives deeper into how Google MailPilot’s plumbing works in production: the new booking-link APIs, security-hardening steps, and embedding telemetry that keep the platform reliable.

## Booking-link APIs & workflows

MailPilot adds dedicated booking-link helpers so invitees can reserve time without needing Gmail credentials.

| Endpoint | Purpose |
|----------|---------|
| `GET /book/{link_id}` | Renders the public booking page (`calendar_booking.html`) for the configured link (title, duration, description). |
| `GET /api/calendar/booking-slots?link_id={link_id}` | Returns up to 20 available slots based on the link’s availability window, duration, timezone, and working-hours constraints. Slots respect the Engine API’s freebusy data plus the configured `availability_start_hour`/`end_hour`. |
| `POST /api/calendar/book` | Accepts `link_id`, slot `start`/`end`, attendee info (`name`, `email`), and optional `notes`. The Engine API creates the event with `add_meet=True`, stores attendee metadata, and records the booking in the `booking_links` table. |

Use the helpers in `workspace_secretary/db/queries/booking_links.py` to manage links programmatically:

- `upsert_booking_link(...)` inserts or updates a link definition (duration, host, metadata, active flag).
- `set_booking_link_status(..., is_active)` toggles a link without deleting it.
- `get_booking_link(...)` + `list_booking_links_for_user(...)` provide lookup layers for admin UIs.

The public booking page strictly verifies `(link_id, is_active)` before returning slots. It also enforces working hours (11:00–22:00 by default) and duration, so external guests can’t book outside the host’s constraints.

## Security hardening checklist

1. **Bearer authentication**: Always enable `bearer_auth.enabled: true` in `config.yaml` and rotate tokens regularly (`uuidgen` / `openssl rand`). The MCP server rejects requests without the header `Authorization: Bearer <token>`.
2. **Reverse proxy + TLS**:
   - Use Traefik, Caddy, or Nginx to terminate TLS in front of `workspace-secretary:8000` (MCP) and `:8080` (Web UI/booking). Example Nginx/Caddy configs now mention `Google MailPilot` in the docs.
   - Keep port 8001 internal (engine API) and only expose 8000/8080 via the proxy.
3. **Web UI auth**: Configure `web.auth.method` (`password` + hashed `auth.password_hash`) and `session_secret`. Session cookies are signed and expire after `session_expiry_hours`.
4. **CSRF & headers**: Both the API and web portal enforce CSRF tokens; HTMX requests must provide `X-Requested-With: XMLHttpRequest`. Security headers (`X-Frame-Options`, `Content-Security-Policy`, etc.) are defined in `docs/webserver/security.md`.
5. **Firewall & network**: Lock down ports so only the proxy can reach 8000/8080, and the engine is accessible via localhost only. Expose 8000, 8080 to the proxy; 8001 should never face the public internet.
6. **Monitoring & logs**:
   - Tail `docker compose logs workspace-secretary` to watch syncing, booking, and embedding entries.
   - Use `curl http://localhost:8000/health` to confirm MCP + engine readiness.
   - Keep tokens, config, and `email_cache.db` outside version control; mount `config/` read-only for config and writeable for `token.json`.

## Embedding telemetry & documentation

MailPilot ships with Postgres + pgvector as standard, so embedding telemetry focuses on verifying that indexing is happening and that similarity tools are healthy.

- **Configuration**: `database.embeddings` in `config.yaml` enables embeddings (Gemini or another OpenAI-compatible provider). Dimensions default to 3072 for nuanced business emails; `batch_size` controls how many emails are sent per API call.
- **Telemetry signals**:
  - The engine logs `INFO - Embedding N emails from <folder>` every few minutes when embeddings are enabled; watch for recurring entries to confirm the embeddings loop runs.
  - Use `semantic_search_emails` and `find_related_emails` as health checks. If they return empty despite recent data, inspect Postgres (pgvector tables) or your embeddings provider quota.
  - The `get_embedding_status` tool reports `status: healthy` once indexing catches up; use it in automation (e.g., `tools.mcp.call_tool("get_embedding_status", {})`).
- **Documentation integration**: Updated guides (Getting Started, Semantic Search, Embeddings) now describe the required Postgres setup (`pgvector/pg16` image) and mention `OPENAI_API_KEY` (or Gemini) as the API key used in telemetry loops. Deployers should confirm environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `POSTGRES_PASSWORD`) are present and that Postgres is healthy (`pg_isready`).

## Summary

These platform-level practices ensure Google MailPilot runs as a secure, observable, and reliable command center. Refer back to this guide whenever you instrument new metrics, roll out booking links, or harden your deployment in front of real users.