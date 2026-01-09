# OAuth Workaround (Third-Party Credentials)

> **WARNING**: This configuration is **unsupported** and may break at any time. It relies on reusing public Client IDs from popular open-source applications (Thunderbird, GNOME, Mailspring) which are trusted by Google. We strongly recommend creating your own OAuth credentials if possible.

If you cannot create a Google Cloud Platform project (e.g., due to organizational restrictions), you can use the public credentials of known open-source email clients.

## How It Works

Third-party OAuth credentials (like Mozilla Thunderbird's) include the `https://mail.google.com/` scope which grants IMAP/SMTP access. Secretary MCP uses this scope for all operations.

## Known Public Credentials

These credentials belong to widely used open-source projects, generally whitelisted by Google.

### Mozilla Thunderbird (Recommended)

**Source**: [OAuth2Providers.sys.mjs](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/base/src/OAuth2Providers.sys.mjs)

```
Client ID:     406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com
Client Secret: kSmqreRr0qwBWJgbf5Y-PjSU
```

**Scopes**:
- `https://mail.google.com/` (IMAP/SMTP)
- `https://www.googleapis.com/auth/calendar` (CalDAV)

### GNOME Online Accounts

**Source**: [meson_options.txt](https://gitlab.gnome.org/GNOME/gnome-online-accounts/-/blob/master/meson_options.txt)

Search for `google_client_id` and `google_client_secret` in the file.

### Evolution Data Server

**Source**: [CMakeLists.txt](https://gitlab.gnome.org/GNOME/evolution-data-server/-/blob/master/CMakeLists.txt)

Search for `GOOGLE_CLIENT_ID` in the file.

### Mailspring (Encrypted)

**Source**: [onboarding-constants.ts](https://github.com/Foundry376/Mailspring/blob/master/app/internal_packages/onboarding/lib/onboarding-constants.ts)

Mailspring encrypts its OAuth secrets. Client ID:
```
662287800555-0a5h4ii0e9hil1dims8hn5opk76pce9t.apps.googleusercontent.com
```

**Encrypted Secret** (AES-256-CTR):
```
Ciphertext (base64): 1EyEGYVh3NBNIbYEdpdMvOzCH7+vrSciGeYZ1F+W6W+yShk=
IV (base64):         wgvAx+N05nHqhFxJ9I07jw==
Key:                 don't-be-ev1l-thanks--mailspring
```

See Mailspring source for decryption code if needed.

## Setup Steps

### 1. Run Auth Setup with Credentials

Use the `--manual` flag (default) which works with any redirect URI:

```bash
# Local development
uv run python -m workspace_secretary.auth_setup \
  --config config.yaml \
  --token-output token.json \
  --client-id "406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com" \
  --client-secret "kSmqreRr0qwBWJgbf5Y-PjSU"
```

### 2. Complete OAuth Flow

1. Open the printed authorization URL in your browser
2. Login and approve access (you'll see "Mozilla Thunderbird" on the consent screen)
3. After approval, you'll be redirected to a localhost URL (may not load—that's OK)
4. **Copy the full URL** from your browser's address bar
5. Paste the URL when prompted
6. Tokens are saved to `token.json`

**Example:**
```
Authorization URL: https://accounts.google.com/o/oauth2/v2/auth?client_id=...

Open the URL above in your browser.
After authorizing, paste the redirect URL here: http://localhost:8080/callback?code=4/0AfJoh...

✓ Authorization successful! Tokens saved to token.json
```

### 3. Configure Docker (if applicable)

Mount your `token.json` into the container:

```yaml
volumes:
  - ./config.yaml:/app/config.yaml:ro
  - ./token.json:/app/token.json
  - ./config:/app/config
```

### Docker Auth Setup

When running in Docker:

```bash
# Run auth setup inside container
docker exec -it workspace-secretary \
  python -m workspace_secretary.auth_setup \
  --config /app/config.yaml \
  --token-output /app/token.json \
  --client-id "406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com" \
  --client-secret "kSmqreRr0qwBWJgbf5Y-PjSU"
```

The `--manual` flag is default, so you'll paste the redirect URL rather than needing localhost access.

## Redirect URIs by Provider

Each OAuth provider has registered specific redirect URIs with Google:

| Provider | Registered Redirect URIs |
|----------|-------------------------|
| Mozilla Thunderbird | `http://localhost`, `http://localhost:*` (any port) |
| GNOME Online Accounts | `http://127.0.0.1`, `http://localhost` |
| Mailspring | `http://localhost:12141/auth` |

The manual flow (paste redirect URL) bypasses redirect URI issues entirely.

## Limitations

1. **Consent Screen**: Shows the provider name (e.g., "Mozilla Thunderbird"), not your app name
2. **Quota Sharing**: You share quota with all users of that client ID
3. **Future Blocking**: Google may rotate secrets or revoke access at any time
4. **No Gmail Labels API**: These credentials only provide IMAP access, but Secretary MCP uses IMAP for everything anyway

## Troubleshooting

### "Access blocked: This app's request is invalid"

The provider's client ID may have been revoked. Try a different provider from the list.

### "Authentication failed" During SMTP Send

Re-run auth setup to refresh tokens:

```bash
uv run python -m workspace_secretary.auth_setup \
  --config config.yaml \
  --token-output token.json \
  --client-id "..." \
  --client-secret "..."
```

### Token Refresh Fails

Third-party credentials may have limited refresh token lifetimes. Re-authenticate if you see persistent 401 errors.

---

**Recommendation**: If at all possible, create your own Google Cloud OAuth credentials. It's more reliable and you control the consent screen branding.
