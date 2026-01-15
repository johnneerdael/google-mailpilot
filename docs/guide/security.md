# Security & SSL Setup

This guide covers securing your Google MailPilot MCP server for remote access.

## Bearer Token Authentication

::: danger Critical Security
Without bearer authentication, **anyone who can reach port 8000 has full access to your email**. Always enable it in production.
:::

Enable bearer token authentication to require clients to authenticate before using the MCP server.

### Generating a Secure Token

Use a cryptographically random token, not a simple password:

::: code-group
```bash [macOS / Linux]
# Generate a UUID (recommended)
uuidgen
# Output: A1B2C3D4-E5F6-7890-ABCD-EF1234567890
```

```powershell [Windows PowerShell]
# Generate a UUID
[guid]::NewGuid().ToString()
# Output: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

```bash [OpenSSL (any system)]
# Generate a 32-byte hex string (64 characters)
openssl rand -hex 32
# Output: 7f8a9b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a
```

```python [Python]
import uuid
print(str(uuid.uuid4()))
# Output: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```
:::

### Configuration

Add to your `config.yaml`:

```yaml
bearer_auth:
  enabled: true
  token: "your-generated-uuid-here"
```

::: tip Best Practices
- **Use a UUID or random hex** — not a simple password
- **Never reuse tokens** — each service should have a unique token
- **Keep it secret** — don't commit `config.yaml` to git (it's in `.gitignore`)
- **Rotate periodically** — change the token if you suspect compromise
:::

### Client Configuration

Add the token to your MCP client configuration:

**Claude Code CLI:**
```bash
claude mcp add --transport http workspace-secretary http://your-server:8000/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

**Cursor / VS Code / Other clients:**
```json
{
  "mcpServers": {
    "workspace-secretary": {
      "url": "http://your-server:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

---

## SSL with Reverse Proxy

For production deployments, use a reverse proxy with automatic SSL certificates from Let's Encrypt.

### Option 1: Traefik

Traefik automatically obtains and renews SSL certificates.

**1. Create environment file (`.env`):**
```bash
ACME_EMAIL=your-email@example.com
MCP_DOMAIN=mcp.yourdomain.com
```

**2. Start with Traefik:**
```bash
docker compose -f docker-compose.traefik.yml up -d
```

**3. DNS Configuration:**
Point `mcp.yourdomain.com` to your server's IP address.

**4. Connect clients:**
```json
{
  "mcpServers": {
    "workspace-secretary": {
      "url": "https://mcp.yourdomain.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

### Option 2: Caddy

Caddy provides automatic HTTPS with zero configuration.

**1. Create `Caddyfile`:**
```
mcp.yourdomain.com {
    reverse_proxy workspace-secretary:8000
}
```

**2. Start with Caddy:**
```bash
docker compose -f docker-compose.caddy.yml up -d
```

**3. DNS Configuration:**
Point `mcp.yourdomain.com` to your server's IP address.

Caddy automatically obtains SSL certificates from Let's Encrypt.

---

## Security Checklist

- [ ] Enable `bearer_auth` in config.yaml
- [ ] Use a UUID or random hex token (not a simple password)
- [ ] Deploy behind Traefik or Caddy for SSL in production
- [ ] Configure DNS to point to your server
- [ ] Restrict firewall to ports 80/443 only
- [ ] Keep config.yaml and tokens out of version control
- [ ] Protect `email_cache.db` — it contains your email data (v2.0+)

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `IMAP_MCP_TOKEN` | Override bearer token (takes precedence over config.yaml) |
| `ACME_EMAIL` | Email for Let's Encrypt certificate notifications (Traefik) |
| `MCP_DOMAIN` | Your domain name for SSL certificate |

---

## Troubleshooting

### Certificate not issued
- Ensure DNS is properly configured and propagated
- Check that ports 80 and 443 are open
- Verify ACME_EMAIL is set correctly

### Authentication failed
- Verify token matches between server logs and client config
- Check `Authorization` header format: `Bearer <token>` (with space)
- Ensure bearer_auth.enabled is `true` in config.yaml

### Connection refused
- Verify the server is running: `docker logs workspace-secretary`
- Check reverse proxy logs: `docker logs traefik` or `docker logs caddy`
- Ensure internal Docker network connectivity
