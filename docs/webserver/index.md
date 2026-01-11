# Web Server & UI

Gmail Secretary includes a full-featured web interface for managing your inbox without an MCP client. Built with Flask and HTMX for a responsive, modern experience.

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Interface                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │  Inbox  │  │ Search  │  │  Chat   │  │Settings │        │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │
├─────────────────────────────────────────────────────────────┤
│                    Flask + HTMX                             │
├─────────────────────────────────────────────────────────────┤
│  IMAP Client  │  PostgreSQL  │  Embeddings  │  LLM API     │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Docker (Recommended)

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
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

```bash
docker compose up -d
# Navigate to http://localhost:8080
```

### Local Development

```bash
# Install dependencies
uv sync --extra postgres --extra cohere

# Run web server
uv run python -m workspace_secretary.web.main --config config.yaml
```

## Features

### Inbox View

The main inbox at `/inbox` displays:

| Feature | Description |
|---------|-------------|
| Unread indicators | Bold styling, visual badges |
| Sender & subject | Quick scan with avatars |
| Timestamps | Relative ("2 hours ago") and absolute |
| Snippets | First line preview |
| Pagination | Configurable page size |

#### Folder Navigation

Switch between Gmail folders:
- **INBOX** - Primary inbox
- **[Gmail]/Sent Mail** - Sent emails
- **[Gmail]/Drafts** - Draft emails
- **[Gmail]/All Mail** - All archived mail
- **Custom labels** - Your Gmail labels

### Thread View

Click any email to view the full conversation:

- **Chronological display** - Oldest to newest
- **Sender avatars** - Visual distinction
- **HTML rendering** - Safe, sanitized HTML
- **Attachments** - Download links
- **Reply/Forward** - Action buttons

### Bulk Actions

Select multiple emails with checkboxes:

```
┌──────────────────────────────────────────────────┐
│ ☑ Select All    [Mark Read] [Archive] [Delete]   │
├──────────────────────────────────────────────────┤
│ ☑ Newsletter from Company A                      │
│ ☑ Weekly Digest #234                             │
│ ☐ Important: Q4 Budget Review                    │
│ ☑ Your order has shipped                         │
└──────────────────────────────────────────────────┘
```

Available actions:
- **Mark as Read** - Clear unread status
- **Mark as Unread** - Flag for attention
- **Archive** - Move to All Mail
- **Delete** - Move to Trash
- **Apply Label** - Add Gmail label

::: warning Confirmation Required
All bulk actions require confirmation before executing.
:::

### Search

#### Basic Search

Quick keyword search across subject and body:

```
┌─────────────────────────────────────┐
│ 🔍 Search emails...          [Search] │
└─────────────────────────────────────┘
```

#### Advanced Filters

Click "Advanced" for detailed filtering:

| Filter | Description | Example |
|--------|-------------|---------|
| From | Sender email/name | `john@company.com` |
| To | Recipient | `me@gmail.com` |
| Subject | Subject keywords | `Q4 Budget` |
| Date Range | Start and end dates | `2026-01-01` to `2026-01-10` |
| Has Attachment | Filter to emails with files | ✓ |
| Unread Only | Filter to unread | ✓ |

#### Semantic Search

Toggle "Semantic" for AI-powered meaning-based search:

```
┌─────────────────────────────────────────────────┐
│ 🔍 budget concerns                    [Semantic ✓] │
└─────────────────────────────────────────────────┘

Results:
• "Q4 Spending Review" (similarity: 89%)
• "Cost overrun in Project X" (similarity: 84%)
• "We need to reduce expenses" (similarity: 78%)
```

Requires [embeddings configuration](/embeddings/).

#### Saved Searches

Save frequently-used searches:

1. Enter search criteria
2. Click "Save Search"
3. Name it (e.g., "VIP Unread")
4. Access from "Saved" dropdown

### AI Chat

Interactive AI assistant at `/chat`:

```
┌─────────────────────────────────────────────────┐
│ 🤖 AI Assistant                                  │
├─────────────────────────────────────────────────┤
│                                                  │
│ User: Summarize my unread emails                │
│                                                  │
│ Assistant: You have 12 unread emails:           │
│ • 3 from VIP contacts (Sarah, John, CEO)        │
│ • 5 newsletters                                  │
│ • 2 calendar invites                            │
│ • 2 automated notifications                     │
│                                                  │
│ Priority: Sarah's email about Q4 budget needs   │
│ attention - she's asking for approval by EOD.   │
│                                                  │
├─────────────────────────────────────────────────┤
│ 💬 Ask anything...                      [Send]   │
└─────────────────────────────────────────────────┘
```

**Capabilities**:
- Summarize emails and threads
- Search by natural language
- Draft replies (requires approval to send)
- Check calendar availability
- Triage and prioritize

**Example prompts**:
- "What emails need my attention today?"
- "Find emails about the Q4 budget"
- "Draft a reply to Sarah saying I'll review it tomorrow"
- "What meetings do I have this week?"

### Settings

Configure preferences at `/settings`:

#### Account
- View connected email account
- Check sync status
- View folder list

#### Display
- Emails per page (10, 25, 50, 100)
- Default folder
- Date format

#### Notifications
- Enable browser notifications
- Notification sound
- Quiet hours

### Notifications

Browser notifications for new emails:

1. Click bell icon in navigation
2. Grant permission when prompted
3. Receive alerts for new unread emails

```javascript
// Notification example
{
  title: "New email from Sarah",
  body: "Q4 Budget Review - Please approve by EOD",
  icon: "/static/icon.png"
}
```

## Configuration

### Environment Variables

```bash
# Required: Email configuration (via config.yaml)
CONFIG_PATH=/app/config/config.yaml

# Optional: AI Chat
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o

# Optional: Semantic Search (Gemini recommended)
EMBEDDINGS_PROVIDER=gemini
EMBEDDINGS_API_KEY=your-gemini-api-key
EMBEDDINGS_MODEL=text-embedding-004

# Optional: Server settings
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_DEBUG=false
```

### Full Docker Compose

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI
    volumes:
      - ./config:/app/config
    environment:
      # AI Chat
      - LLM_API_BASE=https://api.openai.com/v1
      - LLM_API_KEY=${OPENAI_API_KEY}
      - LLM_MODEL=gpt-4o
      # Semantic Search (Gemini recommended)
      - EMBEDDINGS_PROVIDER=gemini
      - EMBEDDINGS_API_KEY=${GEMINI_API_KEY}
      - EMBEDDINGS_MODEL=text-embedding-004
      - ENGINE_API_URL=http://127.0.0.1:8001
    depends_on:
      - postgres

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

## API Endpoints

### HTML Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to `/inbox` |
| `/inbox` | GET | Inbox view |
| `/inbox?folder=FOLDER` | GET | Specific folder |
| `/thread/<id>` | GET | Thread view |
| `/search` | GET/POST | Search interface |
| `/chat` | GET/POST | AI chat |
| `/settings` | GET/POST | User settings |

### JSON API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/emails` | GET | List emails (JSON) |
| `/api/email/<uid>` | GET | Email details (JSON) |
| `/api/search` | POST | Search emails (JSON) |
| `/api/folders` | GET | List folders (JSON) |

### HTMX Partials

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/partials/email-list` | GET | Email list fragment |
| `/partials/email-row/<uid>` | GET | Single email row |
| `/partials/thread/<id>` | GET | Thread fragment |

## Mobile Support

The web UI is fully responsive:

### Breakpoints

| Screen | Layout |
|--------|--------|
| Desktop (>1024px) | Two-column: sidebar + content |
| Tablet (768-1024px) | Collapsible sidebar |
| Mobile (<768px) | Single column, hamburger menu |

### Touch Optimizations

- Large tap targets (44px minimum)
- Swipe gestures for actions
- Pull-to-refresh
- Bottom navigation on mobile

## Security

::: danger Production Warning
The web UI has no built-in authentication. Do not expose directly to the internet.
:::

### Recommended Setup

Use a reverse proxy with authentication:

#### Nginx + Basic Auth

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

#### Caddy + OAuth

```caddyfile
mail.yourdomain.com {
    forward_auth authelia:9091 {
        uri /api/verify?rd=https://auth.yourdomain.com
        copy_headers Remote-User Remote-Groups Remote-Email
    }
    reverse_proxy workspace-secretary:8080
}
```

#### Cloudflare Access

1. Add your domain to Cloudflare
2. Create Access Application
3. Configure identity provider
4. Set policy (email domain, specific users, etc.)

### Security Headers

The web UI sets these security headers:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'
```

### CSRF Protection

All forms include CSRF tokens. API endpoints require:
- Session cookie, or
- `X-Requested-With: XMLHttpRequest` header

## Customization

### Theming

Override CSS variables in `/static/css/custom.css`:

```css
:root {
    --primary-color: #4A90D9;
    --background-color: #ffffff;
    --text-color: #333333;
    --border-color: #e0e0e0;
    --hover-color: #f5f5f5;
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
    :root {
        --background-color: #1a1a1a;
        --text-color: #e0e0e0;
        --border-color: #333333;
        --hover-color: #2a2a2a;
    }
}
```

### Templates

Templates are in `workspace_secretary/web/templates/`:

```
templates/
├── base.html           # Base layout
├── inbox.html          # Inbox view
├── thread.html         # Thread view
├── search.html         # Search page
├── chat.html           # AI chat
├── settings.html       # Settings page
└── partials/
    ├── email-list.html
    ├── email-row.html
    └── nav.html
```

## Troubleshooting

### Page Not Loading

```
Connection refused
```

**Solutions**:
1. Check container is running: `docker ps`
2. Check logs: `docker logs workspace-secretary`
3. Verify port mapping: `-p 8080:8080`

### AI Chat Not Working

```
AI features unavailable
```

**Solutions**:
1. Set environment variables:
   ```bash
   LLM_API_BASE=https://api.openai.com/v1
   LLM_API_KEY=sk-your-key
   LLM_MODEL=gpt-4o
   ```
2. Check API key is valid
3. Check logs for errors

### Semantic Search Not Working

```
Semantic search unavailable
```

**Solutions**:
1. Configure embeddings (see [Embeddings Guide](/embeddings/))
2. Set environment variables:
   ```bash
   EMBEDDINGS_PROVIDER=cohere
   EMBEDDINGS_API_KEY=your-key
   ```
3. Ensure PostgreSQL is running with pgvector

### Slow Performance

**Solutions**:
1. Increase page size limit
2. Add database indexes
3. Enable connection pooling
4. Use pagination for large folders

## Next Steps

- [Embeddings Guide](/embeddings/) - Enable semantic search
- [MCP Tools Reference](/tools/) - Complete tool documentation
- [Agent Patterns](/guide/agents) - Build AI workflows
- [Configuration Guide](/guide/configuration) - Full config reference
