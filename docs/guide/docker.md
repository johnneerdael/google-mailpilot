# Docker Deployment

Deploy Google Workspace Secretary MCP with Docker for persistent email caching and reliable operation.

## Prerequisites

- Docker and Docker Compose installed
- A `config.yaml` file prepared (see [Configuration](./configuration))
- OAuth tokens in `token.json` (see [Getting Started](/getting-started))

## Quick Start

**1. Clone and configure:**

```bash
git clone https://github.com/johnneerdael/Google-Workspace-Secretary-MCP.git
cd Google-Workspace-Secretary-MCP

# Create config directory
mkdir -p config

# Copy sample config
cp config.sample.yaml config.yaml
```

**2. Generate a secure bearer token:**

::: code-group
```bash [macOS]
uuidgen
```

```bash [Linux]
# uuidgen (install uuid-runtime if not available)
uuidgen

# Or use OpenSSL (always available)
openssl rand -hex 32
```

```powershell [Windows]
[guid]::NewGuid().ToString()
```
:::

::: tip Linux Note
On some Linux distributions, `uuidgen` requires the `uuid-runtime` package:
```bash
# Debian/Ubuntu
sudo apt install uuid-runtime

# RHEL/CentOS/Fedora  
sudo dnf install util-linux
```
:::

Add to `config.yaml`:

```yaml
bearer_auth:
  enabled: true
  token: "your-generated-uuid-here"
```

**3. Run OAuth setup locally first:**

```bash
uv run python -m workspace_secretary.auth_setup \
  --config config.yaml \
  --token-output token.json
```

**4. Start the service:**

```bash
docker compose up -d
```

**5. Monitor initial sync:**

```bash
docker compose logs -f
```

## Volume Mounts

The container requires specific volume mounts:

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `./config.yaml` | `/app/config.yaml` | `:ro` | Configuration (read-only) |
| `./token.json` | `/app/token.json` | (rw) | OAuth tokens (read-write) |
| `./config/` | `/app/config/` | (rw) | SQLite cache storage |

::: warning Critical: Correct Mount Pattern
```yaml
# ✅ Correct - config read-only, token read-write
volumes:
  - ./config.yaml:/app/config.yaml:ro
  - ./token.json:/app/token.json
  - ./config:/app/config

# ❌ Wrong - old pattern, config overwrites possible
volumes:
  - ./config:/app/config  # Token inside config dir
```
:::

**Why separate token.json?**
- `config.yaml` is read-only (`:ro`) for security
- `token.json` must be read-write for OAuth token refresh
- Prevents accidental config overwrites during token updates

## Email Cache Behavior

### Initial Sync

On first startup, the server syncs your mailbox to SQLite:

1. Connects to Gmail IMAP
2. Downloads email metadata and bodies in batches
3. Stores in `config/email_cache.db`
4. Progress logged: `Syncing INBOX: 500/2500 emails...`

**Sync times by mailbox size:**
| Emails | Time |
|--------|------|
| ~1,000 | 1-2 minutes |
| ~10,000 | 5-10 minutes |
| ~25,000 | 15-30 minutes |

### Incremental Sync

After initial sync, background sync runs every 5 minutes:
- Checks for new emails via UIDNEXT
- Downloads only new messages
- Removes deleted emails
- Typical sync: < 1 second

### Cache Management

**Reset the cache** (re-download all emails):
```bash
docker compose stop
rm config/email_cache.db
docker compose start
```

**View cache stats**:
```bash
docker exec workspace-secretary sqlite3 /app/config/email_cache.db \
  "SELECT folder, COUNT(*) as emails FROM emails GROUP BY folder;"
```

## Authentication in Docker

### OAuth Setup Inside Container

If you didn't run OAuth setup locally, run it inside the container:

```bash
docker exec -it workspace-secretary \
  python -m workspace_secretary.auth_setup \
  --config /app/config.yaml \
  --token-output /app/token.json
```

The `--manual` flag is default: paste the redirect URL rather than needing localhost access.

### Token Refresh

Tokens auto-refresh. If refresh fails:

```bash
# Re-run auth setup
docker exec -it workspace-secretary \
  python -m workspace_secretary.auth_setup \
  --config /app/config.yaml \
  --token-output /app/token.json

# Restart container
docker compose restart
```

## Environment Variables

Override settings via environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `WORKSPACE_TIMEZONE` | IANA timezone | From config.yaml |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `WORKING_HOURS_START` | Working hours start | From config.yaml |
| `WORKING_HOURS_END` | Working hours end | From config.yaml |

Example:
```yaml
environment:
  - WORKSPACE_TIMEZONE=Europe/London
  - LOG_LEVEL=DEBUG
```

## Health Checks

The container includes health checks:

```bash
# Check health status
docker inspect workspace-secretary --format='{{.State.Health.Status}}'
```

## Production Recommendations

### Resource Limits

For large mailboxes (10k+ emails):

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

Prevent disk fill:

```yaml
services:
  workspace-secretary:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Reverse Proxy Setup

### Traefik

```yaml
# docker-compose.traefik.yml
services:
  workspace-secretary:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.secretary.rule=Host(`secretary.example.com`)"
      - "traefik.http.routers.secretary.tls.certresolver=letsencrypt"
      - "traefik.http.services.secretary.loadbalancer.server.port=8000"
```

### Caddy

```yaml
# docker-compose.caddy.yml with Caddyfile
secretary.example.com {
    reverse_proxy workspace-secretary:8000
}
```

::: warning Caddy Let's Encrypt Caveats
Caddy's automatic HTTPS has requirements:

**Must be true:**
- Ports 80/443 reachable from internet (HTTP-01 challenge)
- DNS A/AAAA record points to your server
- No firewall blocking ACME challenges

**Common failures:**
- ISP blocks port 80
- Behind NAT without port forwarding
- CDN/proxy interfering with challenges
- IPv6 AAAA record exists but IPv6 routing broken

**For wildcards or DNS challenges:**
See [Caddy DNS Challenge documentation](https://caddyserver.com/docs/automatic-https#dns-challenge) for provider-specific setup.
:::

## Connecting Clients

The server exposes a **Streamable HTTP** endpoint at:

```
http://localhost:8000/mcp
```

With bearer auth:
```
Authorization: Bearer your-generated-uuid-here
```

See the [Client Setup Guide](./clients) for Claude Desktop, VS Code, Cursor, and other MCP clients.

## PostgreSQL (Semantic Search)

For AI-powered semantic search, use PostgreSQL with pgvector:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

See [Semantic Search](./semantic-search) for configuration details.

## Troubleshooting

### Sync appears stuck

```bash
docker compose logs --tail=100 | grep -i error
```

Common causes:
- Invalid OAuth tokens (re-run auth setup)
- Network connectivity issues
- Gmail rate limiting

### Cache corruption

```bash
docker compose stop
rm config/email_cache.db
docker compose start
```

### High memory during initial sync

Large mailboxes use more memory during sync. This normalizes after completion. Increase container memory limits if needed.

### Bearer auth not working

```yaml
bearer_auth:
  enabled: true
  token: "exact-token-from-client-config"
```

Token must match exactly (case-sensitive).

### Container can't write token.json

Ensure `token.json` exists and is writable:

```bash
touch token.json
chmod 644 token.json
```

---

**Next**: Configure [Reverse Proxy Security](./security) for production deployments.
