# Security & SSL Setup

This guide covers securing your Google Workspace Secretary MCP server for remote access.

## Bearer Token Authentication

Enable bearer token authentication to require clients to authenticate before using the MCP server.

### Configuration

Add to your `config.yaml`:

```yaml
bearer_auth:
  enabled: true
  token: "your-secret-token-here"  # Optional: auto-generated if not set
```

If `token` is not specified, a random token is generated on server startup and logged:

```
INFO - Bearer authentication enabled. Token: aBcDeFgHiJkLmNoPqRsTuVwXyZ...
```

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
- [ ] Use a strong, randomly generated token (32+ characters)
- [ ] Deploy behind Traefik or Caddy for SSL
- [ ] Configure DNS to point to your server
- [ ] Restrict firewall to ports 80/443 only
- [ ] Keep config.yaml and tokens out of version control

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
