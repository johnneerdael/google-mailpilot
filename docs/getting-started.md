# Getting Started with Google MailPilot

Google MailPilot is the new name for the Gmail Secretary MCP stack. v5.0.0 is the first release under this brand: it delivers reliable MCP tool registration, Postgres-native storage with pgvector embeddings, synchronous triage/compose tests, and reusable booking links that let invitees schedule meetings without direct Google Calendar access.

::: tip What This Is
Google MailPilot is an AI-native command center for Gmail and Google Workspace. It provides:
- **Signals-first tools** (VIP, deadline, question detection) so LLMs can reason before acting
- **Staged mutations** (drafts, suggested reschedules, booking links) that always wait for your confirmation
- **Time-boxed batch workflows** (`quick_clean_inbox`, `triage_priority_emails`) that surface continuation states instead of timing out
- **PostgreSQL + pgvector** for fast, semantic search, and **booking-link scheduling** via `/book/{link_id}`, `/api/calendar/booking-slots`, and `/api/calendar/book`
:::

## Architecture overview

The release ships as a single Docker Compose deployment that internally runs three coordinated processes:
1. **Engine API** (`workspace_secretary.engine.api`, port 8001, internal) — holds the IMAP connection, manages all mutations/auth, and syncs the database.
2. **MCP Server** (`workspace_secretary.tools`, port 8000) — exposes FastMCP tools that read from Postgres, trigger Engine mutations, and enforce the draft-review-send pattern plus `raw:` continuation handling.
3. **Web UI & booking pages** (`workspace_secretary.web`, port 8080) — displays inbox/calendar views and hosts the public booking experience for `/book/{link_id}`.

All components read/write to **PostgreSQL (SQLite is no longer supported)**. Embeddings require pgvector (configured through `database.embeddings`). Booking-link metadata is stored in `booking_links` and surfaced by `workspace_secretary/db/queries/booking_links.py`.

## Prerequisites

- Docker & Docker Compose ([install Docker Desktop](https://www.docker.com/products/docker-desktop))
- PostgreSQL 16+ with the pgvector extension (required for embeddings, booking links, and the shared database layer)
- Google OAuth2 credentials covering: `https://mail.google.com/` (IMAP/SMTP) and `https://www.googleapis.com/auth/calendar`
- A UUID-based bearer token for MCP clients (Claude Desktop, OpenCode, etc.)

## Quick start

### Step 1: Create configuration

Create `config/config.yaml` (mount this folder into the container). Example:

```yaml
bearer_auth:
  enabled: true
  token: "YOUR-UUID-TOKEN"

identity:
  email: your-email@gmail.com
  full_name: "Your Full Name"
  aliases: []

imap:
  host: imap.gmail.com
  port: 993
  username: your-email@gmail.com
  use_ssl: true

smtp:
  host: smtp.gmail.com
  port: 587
  username: your-email@gmail.com
  use_tls: true

database:
  backend: postgres
  postgres:
    host: postgres
    port: 5432
    database: secretary
    user: secretary
    password: secretarypass
  embeddings:
    enabled: true
    provider: gemini
    gemini_api_key: ${GEMINI_API_KEY}
    gemini_model: text-embedding-004
    dimensions: 3072
    batch_size: 100
    task_type: RETRIEVAL_DOCUMENT

timezone: Europe/Amsterdam
working_hours:
  start: "09:00"
  end: "17:00"
  workdays: [1,2,3,4,5]
vip_senders: []
calendar:
  enabled: true
```

⚠️ `aliases: []`, `vip_senders: []`, and proper timezone strings are required even when empty. OAuth tokens belong in `token.json`, not in this file.

### Step 2: Generate your bearer token

```bash
uuidgen  # macOS/Linux
```

Or on Linux: `openssl rand -hex 32`. On Windows PowerShell: `[guid]::NewGuid().ToString()`.

Add the resulting UUID to `bearer_auth.token`. Claude, OpenCode, and other MCP clients will use that value.

### Step 3: Start the stack

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/google-mailpilot:latest
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI + booking pages
    volumes:
      - ./config:/app/config
    environment:
      - LOG_LEVEL=INFO
      - ENGINE_API_URL=http://127.0.0.1:8001
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: secretary
      POSTGRES_USER: secretary
      POSTGRES_PASSWORD: secretarypass
    volumes:
      - postgres_data:/var/lib/postgresql/data
volumes:
  postgres_data:
```

Start everything:

```bash
docker compose up -d
docker compose logs -f
echo "GET http://localhost:8000/health" | xargs curl -sS
```

### Step 4: Run OAuth setup

```bash
docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \
  --client-id='YOUR_CLIENT_ID.apps.googleusercontent.com' \
  --client-secret='YOUR_CLIENT_SECRET'
```

Follow the printed URL, authorize the app, copy the full redirect URL, and paste it back into the shell. Tokens land in `/app/config/token.json`.

:::

### Step 5: Verify everything

```bash
docker compose ps
docker compose logs -f workspace-secretary
curl http://localhost:8000/health
```

## Booking links + scheduling

MailPilot v5 adds an entire public booking flow:

1. Define a booking link (via the Postgres table or your own admin UI) with `link_id`, meeting title, duration, availability window, timezone, and metadata.
2. Share `https://your-domain/book/{link_id}` or embed the public page.
3. The booking page calls `/api/calendar/booking-slots?link_id={link_id}` to show availability (availability hours, duration, and busy windows are respected).
4. Guests post to `/api/calendar/book` with `link_id`, slot start/end, attendee info, and notes. MailPilot creates the event with `add_meet=True`, records the attendee, and saves the event metadata.

The helper module `workspace_secretary/db/queries/booking_links.py` handles inserts, status toggles, and metadata serialization. Toggle `is_active` to disable a link without deleting it.

## Connect your AI client

MCP endpoint: `http://localhost:8000/mcp`  
Web UI: `http://localhost:8080`

Claude Desktop (macOS `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "google-mailpilot": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

Claude Code CLI:

```bash
claude mcp add --transport http google-mailpilot http://localhost:8000/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

## Production deployment patterns

### With Traefik

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.mcp.rule=Host(`mcp.yourdomain.com`)"
  - "traefik.http.routers.mcp.tls.certresolver=letsencrypt"
```

### With Caddy

Use `caddy:2-alpine` to front the MCP server:

```
mcp.yourdomain.com {
    reverse_proxy workspace-secretary:8000
}
```

Ensure ports 80/443 are reachable and DNS points to your host.

## Semantic search & PostgreSQL

PGVector is required for embedding-based search and the new `semantic_search_*` tools. Configure:

```yaml
database:
  backend: postgres
  postgres:
    host: postgres
    port: 5432
    database: secretary
    user: secretary
    password: ${POSTGRES_PASSWORD}
  embeddings:
    enabled: true
    provider: gemini
    gemini_api_key: ${GEMINI_API_KEY}
    gemini_model: text-embedding-004
    dimensions: 3072
    batch_size: 100
    task_type: RETRIEVAL_DOCUMENT
```

`docker compose -f docker-compose.postgres.yml up -d` spins up the Postgres service with pgvector.

## Troubleshooting

- **OAuth "App not verified"**: Click **Advanced** → **Go to [App Name] (unsafe)**.
- **Token refresh fails**: rerun the auth setup command above to regenerate `token.json`.
- **Engine not running**: inspect `workspace-secretary-engine` logs and ensure port 8001 is available.
- **Postgres down**: verify the `postgres` service is healthy (`docker compose ps`) and pgvector is installed (image: `pgvector/pgvector:pg16`).

## Next steps

- Review the [Configuration Guide](/guide/configuration) for advanced tuning.
- Explore the [MCP Tools Reference](/tools/) for the `raw:` continuation convention, triage flows, and booking APIs.
- Study the [Semantic Search Guide](/guide/semantic-search) and [Embeddings pages](/embeddings/) for meaning-based queries.
- Read the [Agent Patterns](/guide/agents) to see how Morning Briefings, triage loops, and safety workflows are implemented.

---

**Need help?** [Open an issue on GitHub](https://github.com/johnneerdael/google-mailpilot/issues)
