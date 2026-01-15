# Docker Deployment

Deploy Google MailPilot with Docker for persistent email caching, booking links, and reliable safety controls.

## Prerequisites

- Docker and Docker Compose installed
- Google Cloud OAuth credentials (client ID + secret) or Gmail App Password
- Basic familiarity with YAML configuration

## Quick Start

**1. Clone and configure:**

```bash
git clone https://github.com/johnneerdael/google-mailpilot.git
cd google-mailpilot

# Create config directory
mkdir -p config

# Copy sample config
cp config.sample.yaml config/config.yaml
```

**2. Generate a secure bearer token:**

::: code-group
```bash [macOS]
uuidgen
```

```bash [Linux]
uuidgen  # or: openssl rand -hex 32
```

```powershell [Windows]
[guid]::NewGuid().ToString()
```
:::

Add to `config/config.yaml`:

```yaml
bearer_auth:
  enabled: true
  token: "your-generated-uuid-here"
```

**3. Start the container:**

```bash
docker compose up -d
```

**4. Run authentication setup:**

```bash
# Option 1: OAuth2 (recommended)
docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \
  --client-id='YOUR_CLIENT_ID.apps.googleusercontent.com' \
  --client-secret='YOUR_CLIENT_SECRET'

# Option 2: App Password (no Google Cloud project needed)
docker exec -it workspace-secretary uv run python -m workspace_secretary.app_password
```

::: tip Simplified auth
Tokens automatically save to `/app/config/token.json`; you don't need to pass `--token-output`.
:::

**5. Monitor sync progress:**

```bash
docker compose logs -f
```

You should see:
```
INFO - Synced 50 new emails from INBOX
INFO - Embedding 50 emails from INBOX
```

## Database Backends

### PostgreSQL with pgvector (Production)

Google MailPilot requires Postgres + pgvector for semantic search, booking links, and shared state between the MCP server, Engine API, and web portal. Configure:

```yaml
database:
  backend: postgres
  host: postgres
  port: 5432
  name: secretary
  user: secretary
  password: ${POSTGRES_PASSWORD}

  embeddings:
    enabled: true
    model: text-embedding-004
    dimensions: 3072
    task_type: RETRIEVAL_DOCUMENT
```

**Postgres unlocks:**
- `semantic_search_emails` / `semantic_search_filtered`
- `find_related_emails`
- Booking link metadata (`booking_links` table)

### SQLite (Development)

SQLite is still available for fast single-user experiments, but lacks semantic search and booking-link support:

```yaml
database:
  backend: sqlite
  path: /app/config/email_cache.db
```

**Docker Compose with PostgreSQL:**

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/google-mailpilot:latest
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI + booking links
    volumes:
      - ./config:/app/config
    environment:
      - POSTGRES_PASSWORD=your-secure-password
      - OPENAI_API_KEY=sk-...  # For embeddings
      - ENGINE_API_URL=http://127.0.0.1:8001
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_USER=secretary
      - POSTGRES_PASSWORD=your-secure-password
      - POSTGRES_DB=secretary
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U secretary"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

See [Semantic Search](./semantic-search) for embedding configuration details.

## Volume Mounts

The container requires a single volume mount:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./config/` | `/app/config/` | Configuration, tokens, and cache |

```yaml
volumes:
  - ./config:/app/config
```

Your `config/` folder contains:
- `config.yaml` - Configuration file
- `token.json` - OAuth tokens (created by auth setup)
- `email_cache.db` - SQLite cache (if using SQLite backend)

::: warning Single folder mount only
```yaml
# ✅ Correct
volumes:
  - ./config:/app/config

# ❌ Wrong - conflicting mounts
volumes:
  - ./config.yaml:/app/config/config.yaml:ro
  - ./config:/app/config
```
:::

## Sync Behavior

### Initial Sync

On first startup:
1. Connects to Gmail IMAP with CONDSTORE support
2. Downloads email metadata and bodies in batches
3. Stores in database (SQLite or PostgreSQL)
4. Generates embeddings if enabled

**Sync times by mailbox size:**
| Emails | Time |
|--------|------|
| ~1,000 | 1-2 minutes |
| ~10,000 | 5-10 minutes |
| ~25,000 | 15-30 minutes |

### Incremental Sync

After initial sync:
- IDLE push notifications for real-time updates
- CONDSTORE for efficient flag change detection
- UIDNEXT tracking for new message detection
- Typical incremental sync: < 1 second

### Cache Management

**Reset the cache:**
```bash
docker compose stop
rm config/email_cache.db  # SQLite only
docker compose start
```

**View sync stats (SQLite):**
```bash
docker exec workspace-secretary sqlite3 /app/config/email_cache.db \
  "SELECT folder, COUNT(*) as emails FROM emails GROUP BY folder;"
```

## Authentication

### OAuth2 Setup

Run inside the container after it's started:

```bash
docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \
  --client-id='YOUR_CLIENT_ID.apps.googleusercontent.com' \
  --client-secret='YOUR_CLIENT_SECRET'
```

The manual OAuth flow:
1. Open the printed authorization URL in your browser
2. Login and approve access
3. Copy the **full redirect URL** (even if page doesn't load)
4. Paste when prompted
5. Tokens saved automatically to `/app/config/token.json`

### App Password Setup

Alternative without Google Cloud project:

```bash
docker exec -it workspace-secretary uv run python -m workspace_secretary.app_password
```

Enter your Gmail address and [App Password](https://myaccount.google.com/apppasswords) when prompted.

### Token Refresh

Tokens auto-refresh. If refresh fails, re-run auth setup and restart:

```bash
docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \
  --client-id='...' --client-secret='...'
docker compose restart
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `POSTGRES_PASSWORD` | PostgreSQL password | Required for postgres backend |
| `OPENAI_API_KEY` | Embeddings API key | Required if embeddings enabled |
| `WORKSPACE_TIMEZONE` | IANA timezone | From config.yaml |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Production Recommendations

### Resource Limits

```yaml
services:
  workspace-secretary:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
```

### Restart Policy

```yaml
services:
  workspace-secretary:
    restart: always
```

### Log Rotation

```yaml
services:
  workspace-secretary:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Connecting Clients

The server exposes a **Streamable HTTP** endpoint at:

```
http://localhost:8000/mcp
```

With bearer auth header:
```
Authorization: Bearer your-generated-uuid-here
```

See the [Client Setup Guide](./clients) for Claude Desktop, VS Code, Cursor, and other MCP clients.

## Port Configuration

The Docker container exposes three services:

| Port | Service | Purpose |
|------|---------|---------|
| 8000 | MCP Server | AI client connections |
| 8001 | Engine API | Internal only (not exposed) |
| 8080 | Web UI | Human interface |

**Port mapping in docker-compose.yml:**
```yaml
ports:
  - "8000:8000"  # MCP server
  - "8080:8080"  # Web UI
  # Note: 8001 is internal only, do not expose
```

## Troubleshooting

### "Database not initialized" error

Ensure the Postgres service is healthy before the MailPilot container starts. The database schema is created on first startup, so restarting once Postgres is ready usually resolves it.

### "Missing client_id or client_secret"

Re-run the OAuth auth setup command above; the helpers now save `client_id`/`client_secret` into `token.json` automatically.

### PostgreSQL connection refused

Ensure postgres service is healthy before secretary starts:
```yaml
depends_on:
  postgres:
    condition: service_healthy
```

### Sync appears stuck

```bash
docker compose logs --tail=100 | grep -i error
```

Common causes:
- Invalid OAuth tokens (re-run auth setup)
- Network connectivity issues
- Gmail rate limiting

### High memory during initial sync

Large mailboxes use more memory during sync. Increase container memory limits if needed.

---

**Next**: Configure [Semantic Search](./semantic-search) for AI-powered email discovery.
