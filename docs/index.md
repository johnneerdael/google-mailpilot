---
layout: home

hero:
  name: "Gmail Secretary"
  text: "IMAP/SMTP Client for AI Agents"
  tagline: A production-grade Gmail client engineered for LLM orchestration with RFC-compliant CONDSTORE, IDLE, and native Gmail extensions
  image:
    src: /hero.jpeg
    alt: Gmail Secretary
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/johnneerdael/gmail-secretary-map

features:
  - icon: 📡
    title: RFC-Compliant IMAP
    details: Full IMAP4rev1 with CONDSTORE (RFC 7162) for incremental sync, IDLE (RFC 2177) for push notifications, and CHANGEDSINCE for flag-only updates.
    
  - icon: ⚡
    title: Instant Sync
    details: Skip sync when mailbox unchanged (HIGHESTMODSEQ), fetch only changed flags, instant new mail via IDLE. 10x faster than polling.
    
  - icon: 🏷️
    title: Native Gmail Support
    details: X-GM-THRID threading, X-GM-MSGID stable IDs, X-GM-LABELS as JSONB, X-GM-RAW search syntax. No heuristic threading needed.
    
  - icon: 🗄️
    title: Local-First Cache
    details: SQLite with FTS5 for instant search, or PostgreSQL with pgvector for semantic search. Your AI reads from local DB in milliseconds.
    
  - icon: 🔒
    title: Human-in-the-Loop
    details: AI never sends without approval. Draft-first philosophy with confidence-based batch operations and explicit confirmation.
    
  - icon: 📅
    title: Calendar Integration
    details: Real-time Google Calendar API access with timezone-aware scheduling, availability lookup, and meeting suggestions within working hours.
---

## Quick Start

Install via Docker (recommended):

```yaml
# docker-compose.yml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    container_name: workspace-secretary
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ./config:/app/config
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

## Why Gmail Secretary MCP?

Traditional email clients are built for humans. **Gmail Secretary MCP** is built for AI assistants.

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

## What's New in v4.8.0

**Database Layer Refactoring & Bug Fixes**:

- 🗄️ **Shared Query Modules**: All SQL queries extracted to `db/queries/` modules (56 functions total)
- 📉 **~1,070 Lines Removed**: Eliminated duplicate SQL between engine and web layers
- 🔧 **Bug Fixes**: 
  - Calendar page no longer returns 500 error (missing `strftime` filter)
  - Email sync works correctly (boolean type mismatch fixed)
  - Embedding sync no longer errors (missing methods added)
  - CSRF tokens now sent correctly with HTMX requests

See the [Architecture Documentation](/architecture) for the new database layer structure.

## What's New in v4.7.x

**Critical Bug Fixes**:

- 🔐 **OAuth2 Token Persistence**: Refreshed tokens now properly saved to disk (v4.7.2)
- 🧠 **Embedding Dimensions**: Fixed config path for embedding dimensions (v4.7.1)
- 🗄️ **Shared Database Layer**: New `workspace_secretary/db/` module for unified access

## What's New in v4.6.0

**Calendar Caching & Offline-First Architecture**:

- ⚡ **Instant Calendar Reads**: 10x faster queries via intelligent caching
- 🌐 **Offline-First Events**: Create/edit/delete events without internet
- 🔄 **Background Worker**: Autonomous sync daemon with incremental updates
- 🏷️ **Status Badges**: Visual indicators for pending sync and conflicts
- ⚙️ **Calendar Selection**: Choose which calendars to display in settings

## What's New in v4.4.0

**Web UI Configuration**:

- 📝 **Config Documentation**: Added web UI configuration options to `config.sample.yaml`

## What's New in v4.3.3

**Phase 4 Dashboard**:

- 📊 **Dashboard Stats**: Email statistics overview (total, unread, today's count)
- ⚡ **Priority Queue**: Priority email list with quick actions
- ⌨️ **Keyboard Shortcuts**: j/k navigation, o to open, r to reply

## What's New in v4.3.2

**halfvec Support for High Dimensions**:

- 🧠 **Automatic Quantization**: 16-bit `halfvec` type for dimensions > 2000
- 🔧 **HNSW Fix**: Resolves "column cannot have more than 2000 dimensions" error
- 📉 **50% Storage Savings**: halfvec uses half the space with ~0.1% recall loss

## What's New in v4.3.0

**Gemini Embeddings & Provider Fallback**:

- 🧠 **Google Gemini Provider**: Native `google-genai` SDK with `task_type` optimization
- 🔄 **Automatic Fallback**: Switch providers on rate limit (Cohere → Gemini or vice versa)
- 📊 **L2 Normalization**: Auto-normalizes Gemini vectors for dimensions ≠ 3072
- 📖 **Detailed Guides**: Copy-paste configs with rate limits, sync time estimates, batch calculators

| Provider | Free Tier Sync (25k emails) | Paid Tier Sync |
|----------|----------------------------|----------------|
| Gemini Free | ~25 days (1k RPD limit) | N/A |
| Gemini Tier 1 | N/A | ~17 minutes |
| Cohere Trial | Limited (1k calls/month) | Varies by plan |

See [Embeddings Guide](/embeddings/) for configuration details.

## What's New in v4.2.7

**Gap Sync & Accurate Counters**:

- 🔍 **Set Difference Sync**: Compares IMAP UIDs vs DB UIDs to find exactly what's missing
- 📊 **Real Progress**: Counters reflect actual DB state, not estimates
- 🔧 **Gap Recovery**: Fixes sync when emails were synced from both ends leaving a gap

## What's New in v4.2.6

**Resumable Sync & Stability Fixes**:

- 🔄 **Resume on Restart**: Sync picks up where it left off using stored `uidnext`
- 📡 **IDLE Starts Immediately**: Real-time email detection even during initial sync
- 🛡️ **Embeddings Stability**: Filters invalid texts, prevents 400 errors from empty emails
- 📊 **Accurate Progress**: Shows "Resuming (16000/26000 done, 10000 remaining)"

## What's New in v4.2.5

**Lockstep Sync+Embed Architecture** — Fixes critical race conditions:

- 🔄 **Lockstep Processing**: Sync 50 emails → embed those 50 → repeat (no parallel race)
- 📊 **Oldest-First Sync**: Now processes all emails from oldest to newest UID
- ⚡ **Event Loop Fixes**: Pool init runs in executor, httpx client reused with semaphore
- 🛡️ **Race Condition Fixed**: Embeddings can no longer exceed synced email count

## What's New in v4.2.4

**Parallel Sync & Smart Scheduling**:

- ⚡ **Parallel Folder Sync**: Up to 5 concurrent IMAP connections via connection pool
- 🔄 **IDLE + Catch-up Strategy**: Real-time INBOX push, 30-min periodic catch-up for other folders
- 🎛️ **Configurable**: `MAX_SYNC_CONNECTIONS` and `SYNC_CATCHUP_INTERVAL` env vars

## What's New in v4.2.3

**Fix for IDLE Blocking Issues**:

- Threaded IDLE Operation:
  - Moved `idle_start`, `idle_done`, `idle_check` to a dedicated thread.
  - Prevents event loop blocking during IMAP IDLE.
- Event-loop Safe Communication:
  - Uses `loop.call_soon_threadsafe()` for updates.
- Updated Documentation:
  - Added architecture section for threaded IDLE pattern.

## What's New in v4.2.2

**Bug Fixes & Documentation Overhaul**:

- 🔧 **Database Init Fix**: Engine now properly initializes database connection pool
- 🐘 **PostgreSQL Support**: Docker image includes psycopg drivers out of the box
- 📝 **Sync Logging**: INFO-level logs show sync progress ("Synced N emails from INBOX")
- 📚 **Docs Refresh**: Simplified OAuth setup, added PostgreSQL guide, updated threading docs

## What's New in v4.2.1

**Authentication UX Improvements** — Easier setup with better error messages:

- 🔐 **Fixed OAuth Token Storage**: `auth_setup` now saves `client_id` and `client_secret` in `token.json` (fixes "Missing client_id or client_secret" error)
- 📋 **Better Setup Instructions**: Startup warning now shows both OAuth2 and App Password options
- 🔒 **Hardcoded Config Paths**: Removed user-configurable output paths to prevent misconfiguration

## What's New in v4.2.0

**Calendar API Passthrough** — Simplified architecture with real-time calendar access:

- 🗓️ **Direct API Access**: Calendar operations now go directly to Google Calendar API (no local caching)
- ⚡ **Real-Time Data**: All calendar queries return live data, no sync staleness
- 🧹 **Simplified Architecture**: Removed calendar database tables and sync complexity
- 🔧 **New Endpoints**: Added 6 new calendar API endpoints for fine-grained control

### New Calendar API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/calendar/list` | List all user's calendars |
| `GET /api/calendar/{id}` | Get calendar details |
| `GET /api/calendar/{id}/events/{event_id}` | Get single event |
| `PATCH /api/calendar/{id}/events/{event_id}` | Update event |
| `DELETE /api/calendar/{id}/events/{event_id}` | Delete event |
| `POST /api/calendar/freebusy` | Query free/busy for multiple calendars |

### Removed

- `calendar_cache.py` — Calendar caching layer removed
- `gmail_client.py` — Deprecated Gmail REST API client removed
- `CalendarSync` class — No longer needed without caching
- Calendar database tables (calendars, events, attendees)
- `calendar_cache_path` config option (ignored if present)

## What's New in v4.1.0

**CONDSTORE & IDLE Support** — Efficient incremental sync with push notifications:

- ⚡ **CONDSTORE (RFC 7162)**: Skip sync when mailbox unchanged, fetch only changed flags via CHANGEDSINCE
- 📬 **IMAP IDLE (RFC 2177)**: Push-based notifications for instant new mail detection
- 🏷️ **Gmail Extensions**: Native X-GM-MSGID, X-GM-THRID, X-GM-LABELS support
- 📎 **Attachment Metadata**: `has_attachments` and `attachment_filenames` stored in database
- 🔄 **Debounced Sync**: Mutations trigger 2-second debounced sync to batch rapid changes

### Performance Improvements

| Scenario | Before | After |
|----------|--------|-------|
| Unchanged mailbox | Fetch all UIDs, compare | Skip entirely (HIGHESTMODSEQ) |
| Flag changes only | Re-fetch entire message | Fetch only changed flags |
| New mail detection | 5-minute poll interval | Instant via IDLE |
| Rapid mutations | Sync per mutation | Single batched sync |

## What's New in v4.0.0

**Complete Architecture Rewrite** — Read/Write Split for reliability and consistency:

- 🔄 **Engine Owns All Writes**: Engine now uses `DatabaseInterface` for all database mutations
- 📖 **MCP is Read-Only**: MCP reads directly from database, calls Engine API only for mutations
- 🗄️ **Unified Database**: Both Engine and MCP use the same `DatabaseInterface` abstraction
- 📅 **Integrated Calendar Sync**: Calendar operations now use direct API passthrough (no local caching)
- 🧠 **Auto Embeddings**: Engine generates embeddings automatically after email sync (PostgreSQL)
- 🚀 **Graceful Enrollment**: Engine starts in "no account" mode, auto-connects when OAuth tokens appear

### New Engine API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/calendar/events` | List calendar events in time range |
| `GET /api/calendar/availability` | Get free/busy information |
| `POST /api/email/setup-labels` | Create Secretary label hierarchy |
| `POST /api/email/send` | Send email via Gmail API |
| `POST /api/email/draft-reply` | Create draft reply in Gmail |

See the [Architecture Documentation](/architecture) for the complete technical overview.

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

- [GitHub Repository](https://github.com/johnneerdael/gmail-secretary-map)
- [Report Issues](https://github.com/johnneerdael/gmail-secretary-map/issues)
- [View Releases](https://github.com/johnneerdael/gmail-secretary-map/releases)

---

<div style="text-align: center; margin-top: 40px; color: var(--vp-c-text-2);">
  <p>Built with ❤️ for the AI-native future</p>
  <p style="font-size: 14px;">Licensed under MIT • © 2024-present John Neerdael</p>
</div>
