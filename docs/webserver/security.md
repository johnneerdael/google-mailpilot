<!-- Refactored docs generated 2026-01-13 -->

# Security

::: danger Production Warning
The web UI has no built-in authentication. Do not expose directly to the internet.
:::

## Recommended setup

Use a reverse proxy with authentication.

### Nginx + Basic Auth

```nginx
server {
    listen 443 ssl;
    server_name mail.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mail.yourdomain.com/privkey.pem;

    auth_basic "Gmail Secretary";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy + OAuth/forward-auth (e.g., Authelia)

```caddyfile
mail.yourdomain.com {
    forward_auth authelia:9091 {
        uri /api/verify?rd=https://auth.yourdomain.com
        copy_headers Remote-User Remote-Groups Remote-Email
    }
    reverse_proxy workspace-secretary:8080
}
```

### Cloudflare Access

1. Add your domain to Cloudflare
2. Create an Access Application
3. Configure an identity provider
4. Set policy (email domain, specific users, etc.)

## Security headers

The web UI sets these security headers:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'
```

## CSRF protection

- All forms include CSRF tokens.
- API endpoints require:
  - session cookie, or
  - `X-Requested-With: XMLHttpRequest` header.
