# Google MailPilot

[![Version](https://img.shields.io/badge/version-5.0.0-blue.svg)](https://github.com/johnneerdael/google-mailpilot/releases)
[![Status](https://img.shields.io/badge/status-Public%20Release-blue)](https://github.com/johnneerdael/google-mailpilot)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**The AI-native command center for Gmail and Google Workspace**

Google MailPilot is the renamed successor to Gmail Secretary, built so LLMs can read, triage, respond to, and calendar-manage Gmail with a production-grade MCP control plane.

> **⚠️ Release Notice:** v5.0.0 is the first public release under the Google MailPilot brand; it fixes MCP tool registration, tightens triage/compose coverage, adds new booking-link helpers, and keeps every mutation human-in-the-loop.
>
> **Release highlights:**
> - Tools now register as soon as `workspace_secretary.tools` imports, preventing FastMCP registration bugs.
> - Triage/compose tooling gained synchronous tests plus `tests/test_triage_priority_emails.py` and `tests/test_web_compose.py` to cover CLI-aware workflows.
> - Engine/web routes, booking links, and `raw:` continuation-state handling now align with Google MailPilot expectations.

---

## 🚦 Stability Matrix

We believe in transparency. Here is the current readiness of our stack:

| Component | Status | Stability Notes |
| :--- | :--- | :--- |
| **IMAP Sync Engine** | 🟢 **Stable** | RFC-compliant, IDLE support, tested on >24k emails. |
| **Read Operations** | 🟢 **Stable** | Search, Threading (X-GM-THRID), and Summarization work perfectly. |
| **Write Operations** | 🟡 **Beta** | Draft creation is stable. **Auto-sending is currently disabled** via the [Safety Interceptor](#safety). |
| **Web Dashboard** | 🟠 **Alpha** | Early preview. UI may change rapidly. |

---

**A Google MailPilot IMAP/SMTP control plane for AI agents with calendar integration**

Built for LLMs that need to read, search, triage, and respond to email autonomously. Not just an MCP wrapper — a full-featured IMAP control plane engineered for AI orchestration workflows.

[📚 **Documentation**](https://johnneerdael.github.io/google-mailpilot/) · [🏗️ **Architecture**](#-architecture) · [⚡ **Quick Start**](#-quick-start)

---

## Why This Exists

Most email integrations for AI are thin API wrappers. They poll. They re-fetch. They timeout. They don't understand email threading, modification sequences, or push notifications.

**Google MailPilot** is different. It's a production-grade IMAP control plane that:

- **Syncs intelligently** — CONDSTORE tracks what changed, IDLE pushes new mail instantly
- **Caches locally** — SQLite or PostgreSQL, your AI reads from local DB in milliseconds
- **Understands Gmail** — Native X-GM-THRID threading, X-GM-LABELS, X-GM-RAW search
- **Never sends without approval** — Human-in-the-loop by design, drafts first

---

## 📡 RFC Compliance

We implement these IMAP extensions for efficient, real-time email sync:

| RFC | Extension | What It Does | Benefit |
|-----|-----------|--------------|---------|
| [RFC 3501](https://datatracker.ietf.org/doc/html/rfc3501) | IMAP4rev1 | Core protocol | Full IMAP compliance |
| [RFC 7162](https://datatracker.ietf.org/doc/html/rfc7162) | CONDSTORE | Tracks modification sequences | Skip sync when mailbox unchanged |
| [RFC 7162](https://datatracker.ietf.org/doc/html/rfc7162) | CHANGEDSINCE | Fetch only changed flags | 10x faster incremental sync |
| [RFC 2177](https://datatracker.ietf.org/doc/html/rfc2177) | IDLE | Push notifications | Instant new mail detection |
| [RFC 2971](https://datatracker.ietf.org/doc/html/rfc2971) | ID | Client identification | Better server compatibility |

### Gmail-Specific Extensions

| Extension | Purpose |
|-----------|---------|
| `X-GM-THRID` | Native Gmail thread ID — no heuristic threading needed |
| `X-GM-MSGID` | Stable message identifier across folders |
| `X-GM-LABELS` | Full Gmail label support (stored as JSONB) |
| `X-GM-RAW` | Gmail's powerful search syntax for targeted sync |

---

## ⚡ Performance

Real benchmarks against a 50,000 email mailbox:

| Operation | Traditional IMAP | Google MailPilot |
|-----------|------------------|-----------------|
| Check for new mail | 2-5s (fetch all UIDs) | **< 50ms** (HIGHESTMODSEQ compare) |
| Sync flag changes | Re-fetch messages | **Flags only** (CHANGEDSINCE) |
| New mail notification | 5-min poll interval | **Instant** (IDLE push) |
| Search emails | Server roundtrip | **< 10ms** (local SQLite FTS5) |
| Thread reconstruction | Parse References headers | **Instant** (X-GM-THRID) |

### How CONDSTORE Works

```
Traditional Sync:
  1. SELECT INBOX
  2. FETCH 1:* (FLAGS)        ← Downloads ALL flags every time
  3. Compare with cache
  4. Fetch changed messages

CONDSTORE Sync:
  1. SELECT INBOX
  2. Compare HIGHESTMODSEQ    ← Single integer comparison
  3. If unchanged → done      ← Skip everything
  4. If changed → FETCH 1:* (FLAGS) CHANGEDSINCE <modseq>
                              ← Only changed messages
```

---

## 🏗️ Architecture

Dual-process design separating sync from AI interface:

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Layer (Claude, etc.)                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Server (read-only)                      │
│  • Exposes 25+ tools for email/calendar operations              │
│  • Reads directly from local database                           │
│  • Mutations proxied to Engine API                              │
└─────────────────────────────────────────────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
┌──────────────────────────┐        ┌──────────────────────────┐
│   SQLite / PostgreSQL    │        │     Secretary Engine     │
│  • Email cache (FTS5)    │◀───────│  • IMAP sync (CONDSTORE) │
│  • Gmail labels (JSONB)  │        │  • IDLE monitor          │
│  • Embeddings (pgvector) │        │  • OAuth2 management     │
└──────────────────────────┘        │  • SMTP send/draft       │
                                    └──────────────────────────┘
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │   Gmail IMAP     │
                                    │   Gmail SMTP     │
                                    │   Calendar API   │
                                    └──────────────────┘
```

### Why Two Processes?

| Concern | Engine | MCP Server |
|---------|--------|------------|
| **Sync** | Owns IMAP connection, IDLE loop | Never touches IMAP |
| **Database** | All writes | Read-only |
| **Uptime** | Always running | Scales with AI requests |
| **Credentials** | Holds OAuth tokens | Stateless |

---

## 🎯 AI-Native Features

**Calendar Integration:**
- ⚡ **Instant Calendar Access**: Sub-50ms queries via intelligent caching layer
- 🌐 **Offline-First Operations**: Create/edit/delete events without internet, sync transparently
- 🔄 **Background Sync Worker**: Autonomous daemon syncs every 60s using Google Calendar API sync tokens
- 🏷️ **Status Indicators**: Visual badges show pending/synced/conflict states for offline operations
- ⚙️ **Multi-Calendar Support**: Select which calendars to display via web UI settings

**Email Intelligence:**

### Intelligent Signal Extraction

Every email is analyzed for actionable signals:

```python
signals = {
    "is_addressed_to_me": True,      # In To: field, not just CC
    "mentions_my_name": True,        # Name appears in body
    "has_question": True,            # Contains "?" or question phrases
    "mentions_deadline": True,       # "EOD", "ASAP", "by Friday"
    "mentions_meeting": True,        # Scheduling keywords detected
    "is_from_vip": True,             # Sender in configured VIP list
    "has_attachments": True,         # PDF, DOCX, etc.
    "attachment_filenames": ["Q4_Report.pdf"]
}
```

### Human-in-the-Loop Safety

**The AI never sends email without explicit approval.**

```
User: "Reply to Sarah saying I'll attend the meeting"

AI: I've drafted this reply:

    To: sarah@company.com
    Subject: Re: Team Meeting Tomorrow

    Hi Sarah,

    I'll be there. Looking forward to it!

    Best regards

    Send this email? (yes/no)

User: "yes"
AI: ✓ Email sent successfully
```

### Confidence-Based Batch Operations

Bulk operations require approval with confidence tiers:

| Confidence | Batch Size | Display |
|------------|------------|---------|
| High (>90%) | Up to 100 | Date, From, Subject only |
| Medium (50-90%) | Up to 10 | + First 300 chars of body |
| Low (<50%) | Individual | Full context required |

---

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Gmail account with [App Password](https://support.google.com/accounts/answer/185833) (or OAuth2)
- Google Cloud project (for Calendar integration)

### 1. Clone and Configure

```bash
git clone https://github.com/johnneerdael/google-mailpilot.git
cd google-mailpilot
cp config.sample.yaml config/config.yaml
```

### 2. Edit Configuration

```yaml
# config/config.yaml
imap:
  host: imap.gmail.com
  port: 993
  username: your-email@gmail.com
  password: your-app-password    # Gmail App Password

user:
  email: your-email@gmail.com
  first_name: Your
  last_name: Name
  timezone: America/New_York
  working_hours:
    start: "09:00"
    end: "18:00"
  vip_senders:
    - ceo@company.com
    - important-client@example.com

database:
  backend: sqlite               # or "postgres" for embeddings
  path: /app/config/secretary.db

bearer_auth:
  enabled: true
  token: "generate-with-uuidgen"
```

### 3. Start Services

```bash
docker-compose up -d
```

### 4. Connect Your AI

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "secretary": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer your-token-here"
      }
    }
  }
}
```

---

## 🔧 Available Tools

### Email Operations

| Tool | Description |
|------|-------------|
| `search_emails` | FTS5-powered local search with Gmail query syntax |
| `get_email_details` | Full email content with signals and metadata |
| `get_email_thread` | Complete thread via X-GM-THRID |
| `summarize_thread` | AI-ready thread summary |
| `create_draft_reply` | Draft response (never auto-sends) |
| `send_email` | Send with explicit approval |
| `modify_gmail_labels` | Add/remove Gmail labels |
| `move_email` | Move between folders |

### Calendar Operations

| Tool | Description |
|------|-------------|
| `list_calendar_events` | Events in time range |
| `get_calendar_availability` | Free/busy lookup |
| `create_calendar_event` | Create with timezone support |
| `suggest_reschedule` | Find alternative meeting times |

### Triage Operations

| Tool | Description |
|------|-------------|
| `get_daily_briefing` | Priority emails + today's calendar |
| `triage_priority_emails` | Identify high-priority items |
| `quick_clean_inbox` | Batch cleanup with approval |

### Semantic Search (PostgreSQL + pgvector)

| Tool | Description |
|------|-------------|
| `semantic_search_emails` | Search by meaning, not keywords |
| `find_related_emails` | Similar emails to reference |

---

## 📊 Database Schema

### Email Storage

```sql
CREATE TABLE emails (
    uid INTEGER,
    folder TEXT,
    message_id TEXT UNIQUE,
    gmail_thread_id BIGINT,        -- X-GM-THRID
    gmail_msgid BIGINT,            -- X-GM-MSGID
    gmail_labels JSONB,            -- Full label set
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    date TIMESTAMPTZ,
    internal_date TIMESTAMPTZ,     -- INTERNALDATE
    body_text TEXT,
    body_html TEXT,
    flags TEXT,
    modseq BIGINT,                 -- CONDSTORE sequence
    has_attachments BOOLEAN,
    attachment_filenames JSONB,
    -- FTS5 index on subject, from_addr, to_addr, body_text
);
```

### Folder State (CONDSTORE)

```sql
CREATE TABLE folder_state (
    folder TEXT PRIMARY KEY,
    uidvalidity INTEGER,
    uidnext INTEGER,
    highestmodseq BIGINT           -- For CONDSTORE sync
);
```

---

## 🔒 Security

| Layer | Protection |
|-------|------------|
| **Transport** | TLS 1.2+ for IMAP/SMTP |
| **Authentication** | OAuth2 or App Passwords (never plain passwords) |
| **API** | Bearer token authentication |
| **Data** | Local database, no cloud sync |
| **Actions** | Human approval for all mutations |

### Never Stored

- Plain text passwords
- OAuth refresh tokens in logs
- Email content in error messages

---

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [Architecture](https://johnneerdael.github.io/google-mailpilot/architecture.html) | Deep dive into dual-process design |
| [Configuration](https://johnneerdael.github.io/google-mailpilot/guide/configuration.html) | All config options explained |
| [Agent Rules](https://johnneerdael.github.io/google-mailpilot/guide/agents.html) | HITL safety patterns |
| [API Reference](https://johnneerdael.github.io/google-mailpilot/api/) | Complete tool documentation |

---

## 🛠️ Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run locally
python -m workspace_secretary.engine.api &  # Start engine
python -m workspace_secretary.server        # Start MCP server
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Built for AI agents that take email seriously.</strong><br>
  <a href="https://github.com/johnneerdael/google-mailpilot">GitHub</a> ·
  <a href="https://johnneerdael.github.io/google-mailpilot/">Documentation</a> ·
  <a href="https://modelcontextprotocol.io/">Model Context Protocol</a>
</p>
