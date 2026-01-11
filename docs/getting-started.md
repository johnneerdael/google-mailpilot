# Getting Started

Get up and running with Gmail Secretary MCP in minutes.

::: tip What This Is
**Secretary MCP is an AI-native Gmail client** — not an IMAP library. It provides:
- **Signals** for intelligent reasoning (VIP, deadlines, questions)
- **Staged mutations** requiring user confirmation
- **Time-boxed batches** that never timeout
- **Optional semantic search** via pgvector
:::

## Prerequisites

- **Docker and Docker Compose** installed ([Install Docker Desktop](https://www.docker.com/products/docker-desktop/))
- **Google Cloud Project** with OAuth2 credentials (for IMAP/SMTP authentication and Calendar API)
- **Claude Desktop** or another MCP-compatible AI client

## Quick Start

### Step 1: Create Configuration

Create `config.yaml`:

```yaml
# config.yaml - mount as read-only in Docker

bearer_auth:
  enabled: true
  token: "REPLACE-WITH-YOUR-UUID"  # See Step 2

identity:
  email: your-email@gmail.com
  full_name: "Your Full Name"
  aliases: []  # Empty list if no aliases

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

timezone: Europe/Amsterdam  # IANA format

working_hours:
  start: "09:00"
  end: "17:00"
  workdays: [1, 2, 3, 4, 5]  # Mon-Fri

vip_senders: []  # Add priority senders, or empty list

calendar:
  enabled: true

# Database: sqlite (default) or postgres (for semantic search)
database:
  backend: sqlite
```

::: warning Critical Fields
- `aliases: []` - Required even if empty
- `vip_senders: []` - Required even if empty  
- OAuth tokens go in `token.json`, NOT in config.yaml
:::

### Step 2: Generate Bearer Token

::: code-group
```bash [macOS]
uuidgen
```

```bash [Linux]
# Install uuid-runtime if uuidgen not found
uuidgen
# Or use OpenSSL (always available)
openssl rand -hex 32
```

```powershell [Windows]
[guid]::NewGuid().ToString()
```
:::

Add the generated token to your `config.yaml` under `bearer_auth.token`.

### Step 3: Create Docker Compose

The container runs three processes via supervisord:
- **Engine API** (port 8001, internal) - IMAP sync, mutations, OAuth management
- **MCP Server** (port 8000, exposed) - Tool exposure for AI clients
- **Web UI** (port 8080, exposed) - Human web interface

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    container_name: workspace-secretary
    restart: always
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI
    volumes:
      - ./config:/app/config
    environment:
      - LOG_LEVEL=INFO
      - ENGINE_API_URL=http://127.0.0.1:8001
```

::: tip Three-Process Architecture
The container internally runs three coordinated processes:
1. **Engine API**: Maintains IMAP connection, handles all mutations
2. **MCP Server**: Exposes tools to AI, proxies writes to Engine
3. **Web UI**: Human interface, proxies writes to Engine

The Engine API runs on port 8001 (internal only, not exposed).
:::

### Step 4: Run OAuth Setup

Start the container first, then run auth setup inside it:

```bash
docker compose up -d

# Option 1: OAuth2 (recommended)
docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup \
  --client-id='YOUR_CLIENT_ID.apps.googleusercontent.com' \
  --client-secret='YOUR_CLIENT_SECRET'

# Option 2: App Password (simpler, no Google Cloud project needed)
docker exec -it workspace-secretary uv run python -m workspace_secretary.app_password
```

::: tip Simplified Setup (v4.2.2+)
- Token automatically saves to `/app/config/token.json`
- Config automatically at `/app/config/config.yaml`
- No `--config` or `--token-output` flags needed
:::

**Manual OAuth Flow:**
1. Open the printed authorization URL in your browser
2. Login and approve access
3. Copy the **full redirect URL** from your browser (even if page doesn't load)
4. Paste when prompted
5. Tokens saved automatically

::: tip Minimal credentials.json
If using `--credentials-file` instead of `--client-id/--client-secret`:
```json
{
  "installed": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET"
  }
}
```
:::


### Step 5: Start and Verify

```bash
docker compose up -d
docker compose logs -f

# Test health endpoint
curl http://localhost:8000/health
```

## Google Cloud Setup

### Create OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Google Calendar API**:
   - APIs & Services → Library → Search and enable it
   - Note: Gmail uses IMAP/SMTP (no Gmail API needed)

4. Configure OAuth Consent Screen:
   - APIs & Services → OAuth consent screen
   - User type: **External** (or Internal for Workspace)
   - Add your email as test user
   - Add scopes:
     - `https://mail.google.com/`
     - `https://www.googleapis.com/auth/calendar`

5. Create Credentials:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Download JSON as `credentials.json`

The downloaded `credentials.json` looks like this:

```json
{
  "installed": {
    "client_id": "123456789-abcdefg.apps.googleusercontent.com",
    "project_id": "your-project-name",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "GOCSPX-your-client-secret",
    "redirect_uris": ["http://localhost"]
  }
}
```

::: tip Only Two Fields Matter
The auth setup only uses `client_id` and `client_secret` from this file. You can alternatively pass them directly via `--client-id` and `--client-secret` flags.
:::

::: tip Manual Flow Advantage
The manual OAuth flow works with any redirect URI, including `http://localhost`. Perfect for headless servers and containers. After auth setup completes, `credentials.json` is no longer needed - only `token.json` is used at runtime.
:::

## Production Deployment

### With Traefik

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    volumes:
      - ./config:/app/config
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.mcp.rule=Host(`mcp.yourdomain.com`)"
      - "traefik.http.routers.mcp.tls.certresolver=letsencrypt"
```

### With Caddy

```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data

  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    volumes:
      - ./config:/app/config

volumes:
  caddy_data:
```

**Caddyfile:**
```
mcp.yourdomain.com {
    reverse_proxy workspace-secretary:8000
}
```

::: warning Caddy Let's Encrypt Caveats
Automatic HTTPS requires:
- Ports 80/443 reachable from internet
- DNS A/AAAA record pointing to your server
- No CDN/proxy interference

**Common failures:**
- ISP blocks port 80
- Behind NAT without port forwarding
- IPv6 AAAA exists but routing broken

**For wildcards or complex setups:** Use [DNS challenge](https://caddyserver.com/docs/automatic-https#dns-challenge)
:::

### With PostgreSQL (Semantic Search)

For AI-powered search by meaning:

```bash
cat > .env << 'EOF'
POSTGRES_PASSWORD=your-secure-password
GEMINI_API_KEY=your-gemini-api-key
EOF

docker compose -f docker-compose.postgres.yml up -d
```

Update `config.yaml`:

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

See [Semantic Search Guide](/guide/semantic-search) and [Embeddings Guide](/embeddings/) for details.

## Connecting AI Clients

MCP Server endpoint: `http://localhost:8000/mcp`  
Web UI: `http://localhost:8080`

### Claude Desktop

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "workspace-secretary": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

### Claude Code (CLI)

```bash
claude mcp add --transport http workspace-secretary http://localhost:8000/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

## Troubleshooting

### OAuth "App Not Verified"

Click **Advanced** → **Go to [App Name] (unsafe)**. Normal for development apps.

### Token Refresh Fails

Re-run auth setup:
```bash
uv run python -m workspace_secretary.auth_setup \
  --credentials-file credentials.json \
  --config config.yaml \
  --token-output token.json
```

### Container Won't Start

```bash
docker compose logs workspace-secretary

# Common issues:
# - config.yaml not found: check volume mount paths
# - Invalid timezone: use IANA format (Europe/Amsterdam, not CET)
# - Missing aliases: [] or vip_senders: []
```

### Permission Denied

1. Ensure `token.json` exists: `touch token.json`
2. Verify APIs enabled in Google Cloud Console
3. Check OAuth scopes include Gmail and Calendar

## Next Steps

- [Configuration Guide](/guide/configuration) - All settings explained
- [MCP Tools Reference](/tools/) - Available tools
- [Semantic Search](/guide/semantic-search) - AI-powered email search
- [Agent Patterns](/guide/agents) - Building intelligent workflows

---

**Need help?** [Open an issue on GitHub](https://github.com/johnneerdael/gmail-secretary-map/issues)
