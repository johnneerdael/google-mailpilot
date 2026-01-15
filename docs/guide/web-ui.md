# Web UI

Google MailPilot includes a full-featured web interface for managing your inbox without an MCP client. Access it at `http://localhost:8080` when running the web server.

## Getting Started

### Running the Web Server

```bash
# Using Docker
docker compose up -d

# Or locally with uv
uv run python -m workspace_secretary.web.main --config config.yaml

# The web UI runs on port 8080 by default
```

Navigate to `http://localhost:8080` to access your inbox. The web UI is automatically started by supervisord in the Docker container.

### Environment Variables

The web UI uses these environment variables for optional features:

```bash
# AI Chat (optional)
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o

# Semantic Search (optional, if using Cohere)
EMBEDDINGS_PROVIDER=cohere
EMBEDDINGS_API_KEY=your-cohere-key
EMBEDDINGS_MODEL=embed-v4.0
```

## Features

### Inbox View

The main inbox displays your emails with:

- **Unread indicators** - Bold styling for unread messages
- **Sender and subject** - Quick scan of who sent what
- **Date/time** - Relative timestamps ("2 hours ago")
- **Snippet preview** - First line of email body

#### Bulk Actions

Select multiple emails using checkboxes, then:

- **Mark as Read** - Clear unread status
- **Mark as Unread** - Flag for later attention
- **Archive** - Move to All Mail
- **Delete** - Move to Trash

::: warning Confirmation Required
Bulk actions require confirmation before executing, following the Human-in-the-Loop safety pattern.
:::

### Thread View

Click any email to view the full conversation thread:

- **Chronological messages** - Oldest to newest
- **Sender avatars** - Visual distinction between participants
- **Full body content** - HTML rendered safely
- **Attachments list** - Download links for attached files
- **Reply button** - Opens compose with context

### AI Chat

Access the AI assistant at `/chat` or via the navigation menu.

**What you can do:**

- "Summarize my unread emails"
- "Find emails about the Q4 budget"
- "Draft a reply to Sarah's last email"
- "What meetings do I have today?"

The AI has access to all MCP tools and follows the same safety rules—it will show drafts before sending and confirm destructive actions.

::: tip Requires LLM Configuration
Set `LLM_API_BASE`, `LLM_API_KEY`, and `LLM_MODEL` environment variables to enable AI chat.
:::

### Search

#### Basic Search

Use the search bar for quick keyword searches across subject and body.

#### Advanced Filters

Click "Advanced" to filter by:

- **From** - Sender email or name
- **To** - Recipient
- **Subject** - Subject line keywords
- **Date range** - Start and end dates
- **Has attachment** - Filter to emails with files
- **Unread only** - Filter to unread

#### Semantic Search

When PostgreSQL + embeddings are configured, toggle "Semantic" to search by meaning:

- "emails about project delays" → finds "timeline slipping", "behind schedule"
- "budget discussions" → finds "cost concerns", "Q4 spending"

See [Semantic Search](./semantic-search) for setup instructions.

#### Saved Searches

Save frequently-used searches for quick access:

1. Enter your search criteria
2. Click "Save Search"
3. Name your search (e.g., "VIP Unread")
4. Access from the "Saved" dropdown

### Settings

Access settings at `/settings` or via the gear icon.

#### Account Settings

- View connected email account
- Check sync status
- View folder list

#### Preferences

- **Default folder** - Starting folder on login
- **Emails per page** - Pagination limit
- **Theme** - Light/dark mode (coming soon)

#### Notifications

- Enable/disable browser notifications
- Configure notification sounds
- Set quiet hours

### Notifications

Browser notifications alert you to new emails:

1. Click the bell icon in the navigation
2. Grant notification permission when prompted
3. Receive alerts for new unread emails

::: tip Desktop Notifications
Works best when the tab is open but not focused. For background notifications, consider using the MCP server with a desktop client instead.
:::

## Mobile Support

The web UI is fully responsive:

- **Inbox** - Single-column layout on mobile
- **Thread view** - Collapsible message headers
- **Navigation** - Hamburger menu
- **Actions** - Touch-friendly buttons

## API Endpoints

The web UI exposes these REST endpoints for integration:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/inbox` | GET | Inbox view (HTML) |
| `/thread/<id>` | GET | Thread view (HTML) |
| `/search` | GET/POST | Search with filters |
| `/chat` | GET/POST | AI chat interface |
| `/settings` | GET/POST | User settings |
| `/api/emails` | GET | JSON email list |
| `/api/email/<uid>` | GET | JSON email details |

## Docker Deployment

The standard Docker image includes the web UI:

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/google-mailpilot:latest
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI
    volumes:
      - ./config:/app/config
    environment:
      - LLM_API_BASE=https://api.openai.com/v1
      - LLM_API_KEY=${OPENAI_API_KEY}
      - LLM_MODEL=gpt-4o
      - ENGINE_API_URL=http://127.0.0.1:8001
```

## Authentication

### Built-in Password Authentication

The web UI supports optional password-based authentication configured via `config.yaml`:

```yaml
web:
  theme: dark  # or light
  
  auth:
    method: password  # or "none" for no authentication
    password_hash: "$argon2id$v=19$m=65536,t=3,p=4$..."  # See below
    session_secret: "your-random-secret-here"
    session_expiry_hours: 24
```

#### Generating a Password Hash

**Step 1: Choose your plaintext password** (e.g., `mySecurePassword123`)

**Step 2: Generate the hash**

::: code-group
```bash [Using argon2 (recommended)]
# Install argon2-cffi if needed
pip install argon2-cffi

# Generate hash
python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('mySecurePassword123'))"
```

```bash [Using bcrypt]
# Install bcrypt if needed
pip install bcrypt

# Generate hash
python -c "import bcrypt; print(bcrypt.hashpw(b'mySecurePassword123', bcrypt.gensalt()).decode())"
```

```bash [Using Docker container]
# If you have the container running
docker exec -it workspace-secretary python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('mySecurePassword123'))"
```
:::

**Step 3: Add hash to config.yaml**

Copy the entire hash output (including the `$argon2id$...` prefix) into your config:

```yaml
web:
  auth:
    method: password
    password_hash: "$argon2id$v=19$m=65536,t=3,p=4$abcd1234..."
    session_secret: "generate-with-uuidgen-or-openssl-rand"
    session_expiry_hours: 24
```

**Step 4: Generate session secret**

::: code-group
```bash [macOS]
uuidgen
```

```bash [Linux]
uuidgen
# Or use OpenSSL
openssl rand -hex 32
```

```powershell [Windows]
[guid]::NewGuid().ToString()
```
:::

**Step 5: Restart the web server**

```bash
docker compose restart workspace-secretary
```

#### Logging In

1. Navigate to `http://localhost:8080/auth/login`
2. **Enter your plaintext password** (NOT the hash)
   - If you hashed `mySecurePassword123`, type `mySecurePassword123`
3. Click "Login"

::: warning Common Mistake
**Enter the plaintext password you used to generate the hash**, not the hash itself.

- ✅ Login with: `mySecurePassword123` (what you typed into the hash generator)
- ❌ Don't login with: `$argon2id$v=19$m=65536...` (the hash)
:::

#### No Authentication Mode

For local development only, you can disable authentication:

```yaml
web:
  auth:
    method: none  # No login required
```

⚠️ **Security Warning**: Anyone who can reach your web UI port can access your emails. Only use `method: none` for local development on trusted networks.

### Alternative: Reverse Proxy Authentication

For production deployment, use a reverse proxy with authentication:

#### Example: Nginx + Basic Auth

```nginx
server {
    listen 443 ssl;
    server_name mail.yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mail.yourdomain.com/privkey.pem;
    
            auth_basic "Google MailPilot"
;
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Generate `.htpasswd`:
```bash
htpasswd -c /etc/nginx/.htpasswd yourusername
```

## Security Considerations

The web UI security depends on your authentication method:

| Method | Security Level | Use Case |
|--------|---------------|----------|
| Built-in password auth | Medium | Personal use, trusted network |
| Reverse proxy (nginx/Caddy) | High | Production deployment |
| No authentication | Low | Local development only |

For production deployment:

1. **Enable authentication** - Use built-in or reverse proxy auth
2. **HTTPS** - Always use TLS in production
3. **Network isolation** - Don't expose directly to internet
4. **Strong passwords** - Use long, random passwords
5. **Session expiry** - Configure reasonable session timeout

## Next Steps

- [Configuration Guide](./configuration) - Full config reference
- [Semantic Search](./semantic-search) - Enable AI-powered search
- [Agent Patterns](./agents) - Build intelligent workflows
