---
layout: home

hero:
  name: "Google Workspace Secretary"
  text: "AI-Native MCP Server"
  tagline: Transform Gmail and Google Calendar into an intelligent, AI-powered knowledge base
  image:
    src: /hero-image.svg
    alt: Google Workspace Secretary MCP
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/johnneerdael/Google-Workspace-Secretary-MCP

features:
  - icon: ⚡
    title: Single Container Architecture
    details: v3.1 brings supervisor-managed processes. Engine + MCP server run together with Unix socket IPC—simple deployment, persistent IMAP connections.
    
  - icon: 🤖
    title: AI-Native Design
    details: Built specifically for AI assistants like Claude via Model Context Protocol (MCP). Provides intelligent tools that scaffold complex email and calendar workflows.
    
  - icon: 🧠
    title: Intelligent Prioritization
    details: Daily briefings with ML-ready signals for VIP senders, urgency markers, questions, and deadlines. The AI decides priority based on your context.
    
  - icon: 🌍
    title: Timezone-Aware Scheduling
    details: All calendar operations respect your configured timezone and working hours. Automatically suggests meeting times that fit your schedule.
    
  - icon: 📄
    title: Document Intelligence
    details: Extract and analyze text from PDF, DOCX, TXT, and LOG attachments directly in the AI's context. No manual downloads needed.
    
  - icon: 🔒
    title: Human-in-the-Loop Safety
    details: Built-in safety patterns ensure all mutations (sending emails, deleting, moving) require explicit user confirmation.
---

## Quick Start

Install via Docker (recommended):

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/google-workspace-secretary-mcp:latest
    container_name: workspace-secretary
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config/config.yaml:ro
      - ./token.json:/app/config/token.json
      - ./data:/app/data
    environment:
      - LOG_LEVEL=INFO
```

**Important**: Generate a unique bearer token for security:

```bash
# macOS/Linux
uuidgen

# Windows PowerShell
[guid]::NewGuid().ToString()
```

Add to your `config.yaml`:

```yaml
bearer_auth:
  enabled: true
  token: "your-generated-uuid-here"
```

Then start with: `docker compose up -d`

See [Getting Started](/getting-started) for complete installation instructions.

## Why Google Workspace Secretary MCP?

Traditional email clients are built for humans. **Google Workspace Secretary MCP** is built for AI assistants.

- **Instant reads**: SQLite cache means sub-millisecond email queries
- **Persistent connections**: Engine maintains IMAP connection (no per-request reconnect)
- **Token-efficient**: Bulk email fetching with smart truncation (700 chars) for fast triage
- **Context-rich**: Full thread history, attachment content, and calendar context in one tool call
- **Intelligence signals**: VIP detection, urgency markers, question detection—not hardcoded decisions
- **Agentic workflows**: Compose specialized agents (Triage, Scheduler, Intelligence Clerk) using atomic tools

## Example Workflows

::: tip Daily Briefing
"Give me my daily briefing—what emails need my attention today?"

The AI uses `get_daily_briefing()` to fetch:
- Today's calendar events
- Email candidates with 5 priority signals (VIP, urgent, questions, deadlines, meetings)
- Intelligent summary prioritizing your VIP senders and time-sensitive requests
:::

::: tip Smart Scheduling
"I received a meeting invite from John for tomorrow at 2 PM. Check my calendar and if I'm free during working hours, draft an acceptance."

The AI:
1. Checks calendar availability with `check_calendar()`
2. Validates time is within your `working_hours`
3. Uses `create_draft_reply()` to prepare response
4. Shows you the draft for confirmation
:::

::: tip Document Intelligence
"Find the invoice PDF sent by Accounting last week, read it, and tell me the total amount."

The AI:
1. Searches with `search_emails(keyword='invoice', from='accounting')`
2. Extracts PDF text with `get_attachment_content()`
3. Parses and presents the total
:::

## What's New in v3.2.0

**Standardized Docker Paths & OAuth Consolidation**:

- 📁 **Config Path**: `/app/config/config.yaml` is now the default (Docker-first)
- 🔐 **Single OAuth Entry**: `auth_setup.py` handles all OAuth flows (browser_auth removed)
- 📅 **Calendar Scope**: OAuth now includes Gmail + Calendar scopes by default
- 🛠️ **Token Output**: `--token-output` flag for Docker-friendly token management

## What's New in v3.1.0

**Single Container Architecture** — Simplified deployment with supervisor-managed processes:

- 📦 **One Container**: Engine + MCP server run together via supervisord
- 🔌 **Unix Socket IPC**: Internal communication between processes
- ⚡ **Persistent IMAP**: Engine maintains connection (no per-request reconnect)
- 🔄 **Background Sync**: Continuous incremental sync every 5 minutes
- 📝 **Better Docs**: Added credentials.json example format

## What's New in v3.0.0

**Dual-Process Architecture** — Complete separation of concerns for reliability:

- 🔄 **Engine + MCP Split**: Independent sync daemon + MCP server
- 📅 **Calendar Sync**: Full calendar synchronization with local SQLite cache
- 🧠 **Semantic Search**: Optional PostgreSQL + pgvector backend with embeddings
- ⚡ **Database Options**: SQLite (default) or PostgreSQL with pgvector for AI features
- 🚫 **IMAP-Only**: Removed deprecated API mode (`oauth_mode` config removed)

### Database Options

| Backend | When to Use | Features |
|---------|-------------|----------|
| **SQLite** (default) | Simple deployment, single user | FTS5 keyword search, WAL mode |
| **PostgreSQL + pgvector** | AI features needed | Semantic search, embeddings, similarity matching |

See the [Architecture Documentation](/architecture) for technical details.

## What's New in v2.2.0

**RFC 5256 Threading Support** — Full conversation threading with automatic backfill:

- 🧵 **Server-Side Threading**: Uses IMAP `THREAD` command (RFC 5256) when available
- 🔄 **Automatic Backfill**: Existing emails get thread headers populated on first sync
- 📊 **Thread Data Model**: `in_reply_to`, `references`, `thread_root_uid` stored in SQLite
- ⚡ **Cache-First Threads**: `get_email_thread` queries local cache instead of IMAP

See the [Threading Guide](/guide/threading) for details.

## Previous Releases

<details>
<summary>v2.1.0 and earlier</summary>

### v2.1.0
- 📚 Comprehensive v2.0 documentation overhaul
- 🔧 Fixed sync direction (newest-first for immediate usability)
- 🐛 Cache update fixes for triage tools

### v2.0.0 - Local-First Architecture
- ⚡ **SQLite Cache**: Email queries hit local database—instant response times
- 🔄 **Background Sync**: Continuous incremental sync keeps cache fresh
- 💾 **Persistent Storage**: Cache survives restarts
- 📊 **RFC-Compliant**: Proper UIDVALIDITY/UIDNEXT tracking per RFC 3501/4549

### v1.1.0
- Third-party OAuth Support (Thunderbird/GNOME credentials)
- SMTP with XOAUTH2
- Calendar independent of email backend

### v0.2.0
- Timezone-aware scheduling
- Working hours constraints
- Intelligent email signals
- VIP sender detection

</details>

[See Migration Guide](/guide/configuration#migration-from-v01x) for upgrading from earlier versions.

## Community & Support

- [GitHub Repository](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP)
- [Report Issues](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP/issues)
- [View Releases](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP/releases)

---

<div style="text-align: center; margin-top: 40px; color: var(--vp-c-text-2);">
  <p>Built with ❤️ for the AI-native future</p>
  <p style="font-size: 14px;">Licensed under MIT • © 2024-present John Neerdael</p>
</div>
