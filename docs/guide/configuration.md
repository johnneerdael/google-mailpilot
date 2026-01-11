# Configuration

Complete configuration reference for Gmail Secretary MCP.

## Configuration File

The server requires a `config.yaml` file (read-only) and a `token.json` file (read-write for OAuth tokens).

```bash
# Copy sample config
cp config.sample.yaml config.yaml

# After OAuth setup, token.json is created automatically
```

::: warning Critical: Separate Token Storage
OAuth tokens are stored in `token.json`, NOT in config.yaml. This allows:
- `config.yaml` mounted read-only (`:ro`) for security
- `token.json` mounted read-write for token refresh
- No risk of config overwrites during token updates
:::

## Required Fields

### Bearer Authentication

::: warning Strongly Recommended
Enable bearer auth to protect your email from unauthorized access. Without it, anyone who can reach the server has full access to your email.
:::

```yaml
bearer_auth:
  enabled: true
  token: "your-secure-token-here"
```

**Generate a unique token:**

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

### User Identity

```yaml
identity:
  email: your-email@gmail.com
  full_name: "Your Full Name"
  aliases: []  # Empty list if you have no aliases
```

**Fields:**
- `email` (required): Your primary Gmail address
- `full_name` (optional): Used to detect if you're mentioned in email body
- `aliases` (required): Additional email addresses, or `[]` if none

::: warning Always Include aliases
Even if you have no aliases, you must include the field:
```yaml
aliases: []  # Required - empty list if no aliases
```
:::

**Used by:**
- `get_daily_briefing`: Signals `is_addressed_to_me` and `mentions_my_name`
- `quick_clean_inbox`: Determines which emails can be auto-cleaned

### IMAP Configuration

```yaml
imap:
  host: imap.gmail.com
  port: 993
  username: your-email@gmail.com
  use_ssl: true
```

OAuth credentials are stored in `token.json` after running auth setup—not in config.yaml.

::: tip Gmail-Only
This server is designed for Gmail. While built on IMAP/SMTP protocols, it uses Gmail-specific features (labels, OAuth, threading) that won't work with other providers.
:::

### SMTP Configuration

```yaml
smtp:
  host: smtp.gmail.com
  port: 587
  username: your-email@gmail.com
  use_tls: true
```

Uses the same OAuth token from `token.json` for authentication.

### Timezone

```yaml
timezone: Europe/Amsterdam  # IANA timezone format
```

**Valid formats**: [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) names:
- `America/Los_Angeles` (not `PST`)
- `Europe/London` (not `GMT`)
- `Asia/Tokyo` (not `JST`)

### Working Hours

```yaml
working_hours:
  start: "09:00"  # HH:MM format, 24-hour clock
  end: "17:00"
  workdays: [1, 2, 3, 4, 5]  # 1=Monday, 7=Sunday
```

**Rules**:
- Times must be in `HH:MM` format (e.g., `09:00`, not `9:00 AM`)
- Workdays: `1`=Monday through `7`=Sunday
- Tools like `suggest_reschedule()` only suggest times within these constraints
- Agents will still ask before declining meetings outside working hours

### VIP Senders

```yaml
vip_senders:
  - boss@company.com
  - ceo@company.com
  - important-client@example.com
```

Or if you have no VIPs:

```yaml
vip_senders: []
```

**Rules**:
- Exact email addresses (case-insensitive)
- Emails from these senders get `is_from_vip=true` in signals

## Database Configuration

Secretary MCP supports two database backends for email caching.

### SQLite (Default)

No configuration needed—SQLite is automatic:

```yaml
database:
  backend: sqlite  # Default, can be omitted
```

**Cache location**: `config/email_cache.db` (same directory as config.yaml)

**When to use SQLite:**
- Single-user deployments
- Local development
- Simple setups without semantic search

### PostgreSQL with pgvector

For semantic search capabilities (search by meaning, find related emails):

```yaml
database:
  backend: postgres
  
  postgres:
    host: postgres          # Docker service name, or localhost
    port: 5432
    database: secretary
    user: secretary
    password: ${POSTGRES_PASSWORD}
    ssl_mode: prefer
  
  embeddings:
    enabled: true
    provider: gemini
    gemini_api_key: ${GEMINI_API_KEY}
    gemini_model: text-embedding-004
    dimensions: 3072
    batch_size: 100
    task_type: RETRIEVAL_DOCUMENT
```

**When to use PostgreSQL:**
- Need semantic search ("find emails about budget concerns")
- Want `find_related_emails` for context gathering
- Multi-instance deployments with shared database

See [Semantic Search](./semantic-search) and [Embeddings Guide](/embeddings/) for complete setup.

## Optional Fields

### Allowed Folders

Restrict which folders the AI can access:

```yaml
allowed_folders:
  - INBOX
  - "[Gmail]/Sent Mail"
  - "[Gmail]/All Mail"
```

**Default**: If omitted, all folders are accessible.

::: tip Gmail Folder Names
Gmail uses `[Gmail]/` prefix for system folders:
- `[Gmail]/Sent Mail`
- `[Gmail]/Drafts`
- `[Gmail]/All Mail`
- `[Gmail]/Trash`
:::

### Calendar Configuration

```yaml
calendar:
  enabled: true
```

**Default**: Calendar tools disabled unless explicitly enabled.

### Web UI Configuration

Configure the optional web interface:

```yaml
web:
  theme: dark  # or "light"
  
  auth:
    method: password  # "password" or "none"
    password_hash: "$argon2id$v=19$m=65536,t=3,p=4$..."
    session_secret: "your-random-secret-here"
    session_expiry_hours: 24
```

**Fields:**
- `theme`: UI theme (`dark` or `light`)
- `auth.method`: Authentication method
  - `password`: Require password login
  - `none`: No authentication (local development only)
- `auth.password_hash`: Argon2 or bcrypt hash of your password
- `auth.session_secret`: Random string for session encryption
- `auth.session_expiry_hours`: Session timeout in hours

**Generating a password hash:**

::: code-group
```bash [Argon2 (recommended)]
python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('your-password-here'))"
```

```bash [Bcrypt]
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password-here', bcrypt.gensalt()).decode())"
```

```bash [Docker container]
docker exec -it workspace-secretary python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('your-password-here'))"
```
:::

**Generating session secret:**

```bash
# macOS/Linux
uuidgen

# Or use OpenSSL
openssl rand -hex 32
```

::: warning Login Credentials
When logging into the web UI, enter your **plaintext password** (the one you used to generate the hash), NOT the hash itself.

- ✅ Login with: `your-password-here` (what you hashed)
- ❌ Don't use: `$argon2id$v=19$m=65536...` (the hash)
:::

See [Web UI Guide](./web-ui) for complete setup instructions.

## Environment Variables

All fields can be overridden via environment variables:

| Variable | Config Path | Example |
|----------|-------------|---------|
| `IMAP_HOST` | `imap.host` | `imap.gmail.com` |
| `IMAP_PORT` | `imap.port` | `993` |
| `IMAP_USERNAME` | `imap.username` | `user@gmail.com` |
| `WORKSPACE_TIMEZONE` | `timezone` | `America/New_York` |
| `WORKING_HOURS_START` | `working_hours.start` | `09:00` |
| `WORKING_HOURS_END` | `working_hours.end` | `17:00` |
| `WORKING_HOURS_DAYS` | `working_hours.workdays` | `1,2,3,4,5` |
| `VIP_SENDERS` | `vip_senders` | `boss@co.com,ceo@co.com` |
| `POSTGRES_PASSWORD` | `database.postgres.password` | (secret) |
| `OPENAI_API_KEY` | `database.embeddings.api_key` | `sk-...` |

### Docker Environment Example

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    environment:
      - WORKSPACE_TIMEZONE=America/Los_Angeles
      - WORKING_HOURS_START=09:00
      - WORKING_HOURS_END=17:00
      - VIP_SENDERS=boss@company.com,ceo@company.com
```

## Validation

The server validates your config on startup:

- **Timezone**: Must be valid IANA timezone
- **Working Hours**: Times must be `HH:MM` format
- **Workdays**: Must be integers 1-7
- **VIP Senders**: Normalized to lowercase for matching
- **Aliases**: Must be present (use `[]` if empty)

**Example error**:
```
ValueError: Invalid timezone: 'PST'. Use IANA format like 'America/Los_Angeles'
```

## Configuration Precedence

Order of precedence (highest to lowest):
1. Environment variables
2. `config.yaml` file
3. Default values

## Complete Example

```yaml
# config.yaml - mount as read-only (:ro)

bearer_auth:
  enabled: true
  token: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

identity:
  email: john@gmail.com
  full_name: "John Smith"
  aliases: []  # No aliases

imap:
  host: imap.gmail.com
  port: 993
  username: john@gmail.com
  use_ssl: true

smtp:
  host: smtp.gmail.com
  port: 587
  username: john@gmail.com
  use_tls: true

timezone: America/New_York

working_hours:
  start: "09:00"
  end: "18:00"
  workdays: [1, 2, 3, 4, 5]

vip_senders:
  - manager@company.com
  - ceo@company.com

calendar:
  enabled: true

# Optional: PostgreSQL for semantic search
database:
  backend: sqlite  # or 'postgres' for semantic search
```

## Troubleshooting

### "Invalid timezone" Error

**Problem**: `ValueError: Invalid timezone: 'PST'`

**Solution**: Use IANA format:
```yaml
timezone: America/Los_Angeles  # Not 'PST'
```

### "Working hours must be HH:MM" Error

**Problem**: `ValueError: start time must be in HH:MM format`

**Solution**: Use 24-hour format with leading zeros:
```yaml
working_hours:
  start: "09:00"  # Not "9:00 AM"
```

### OAuth Token Refresh Fails

**Problem**: `401 Unauthorized` after some time

**Solution**: Re-run auth setup to get fresh tokens:
```bash
# Local
uv run python -m workspace_secretary.auth_setup \
  --config config.yaml \
  --token-output token.json

# Docker
 docker exec -it workspace-secretary \
   python -m workspace_secretary.auth_setup \
   --config /app/config/config.yaml \
   --token-output /app/config/token.json

```

### "aliases" Field Missing

**Problem**: Validation error about missing aliases

**Solution**: Always include aliases, even if empty:
```yaml
identity:
  email: john@gmail.com
  aliases: []  # Required!
```

---

**Next**: Learn [Agent Patterns](./agents) for building intelligent workflows.
