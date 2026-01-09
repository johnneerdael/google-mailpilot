# Architecture v3 Plan: Dual-Process Design

## Overview

Refactor from single-process to dual-process architecture:

- **Process A: `secretary-engine`** - Headless email/calendar sync daemon
- **Process B: `secretary-mcp`** - MCP server for AI agent interaction

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  secretary-engine (standalone daemon)                       │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ IMAP Sync   │  │ Calendar    │  │ Internal API      │   │
│  │ (OAuth2)    │  │ Sync        │  │ (Unix Socket)     │   │
│  └──────┬──────┘  └──────┬──────┘  └─────────┬─────────┘   │
│         │                │                   │              │
│         ▼                ▼                   ▼              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              SQLite Databases (WAL mode)            │   │
│  │  • email_cache.db (emails, threads, folders)        │   │
│  │  • calendar_cache.db (events, calendars)            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Unix Socket (mutations)
                           │ SQLite (reads)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  secretary-mcp (MCP server)                                 │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ MCP Tools   │  │ MCP         │  │ Bearer Auth       │   │
│  │ (email,cal) │  │ Resources   │  │ (for clients)     │   │
│  └─────────────┘  └─────────────┘  └───────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Aspect | Engine (A) | MCP (B) |
|--------|------------|---------|
| Auth | OAuth2 (Gmail/Calendar) | Bearer token |
| Lifecycle | Independent, always running | Stateless, can restart |
| Data ownership | Owns SQLite, syncs continuously | Reads from SQLite |
| Mutations | Exposes internal API | Calls Engine API for mutations |
| Entry point | `python -m workspace_secretary.engine` | `python -m workspace_secretary` |

## Internal API (Unix Socket)

Engine exposes FastAPI on Unix socket `/tmp/secretary-engine.sock`:

```
POST /api/email/send              # Send via SMTP
POST /api/email/move              # Move to folder
POST /api/email/mark-read         # Mark as read
POST /api/email/mark-unread       # Mark as unread
POST /api/email/labels            # Modify Gmail labels
POST /api/calendar/event          # Create/update event
POST /api/calendar/respond        # Accept/decline invite
GET  /api/status                  # Health check, sync status
GET  /api/sync/trigger            # Trigger immediate sync
```

## Database Strategy

Based on Oracle research, using **SQLite with WAL mode + FTS5**:

### email_cache.db (existing, enhanced)
- emails, threads, folders, attachments metadata
- sync_state (UIDVALIDITY, UIDNEXT, last_sync)
- FTS5 index for full-text search
- Attachments stored on disk (content-addressed), DB stores path/hash

### calendar_cache.db (new)
```sql
CREATE TABLE calendars (
    id TEXT PRIMARY KEY,
    summary TEXT,
    description TEXT,
    timezone TEXT,
    access_role TEXT,
    sync_token TEXT,
    last_sync TEXT
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    location TEXT,
    start_time TEXT,
    end_time TEXT,
    all_day BOOLEAN,
    status TEXT,
    organizer_email TEXT,
    recurrence TEXT,
    recurring_event_id TEXT,
    html_link TEXT,
    hangout_link TEXT,
    created TEXT,
    updated TEXT,
    etag TEXT,
    FOREIGN KEY (calendar_id) REFERENCES calendars(id)
);

CREATE TABLE attendees (
    event_id TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    response_status TEXT,
    is_organizer BOOLEAN,
    is_self BOOLEAN,
    PRIMARY KEY (event_id, email),
    FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE INDEX idx_events_calendar ON events(calendar_id);
CREATE INDEX idx_events_start ON events(start_time);
CREATE INDEX idx_events_recurring ON events(recurring_event_id);
```

### Calendar Sync Strategy
- Full sync on first run (as far back as API allows)
- Incremental sync via sync tokens
- Recurring events: store RRULE, expand instances on-demand

## Implementation Phases

### Phase 1: Extract Engine Package
- Create `workspace_secretary/engine/` package
- Move: `imap_client.py`, `calendar_client.py`, `cache.py`, `oauth2.py`
- Add: `api.py` (FastAPI on Unix socket)
- Entry point: `python -m workspace_secretary.engine`

### Phase 2: Add Calendar Sync
- Create `calendar_cache.db` schema
- Implement `CalendarSync` class (mirrors existing IMAP sync pattern)
- Full sync + incremental via sync tokens

### Phase 3: Refactor MCP
- Remove direct IMAP/Calendar client usage
- Read operations: direct SQLite queries
- Write operations: call Engine API via Unix socket
- MCP becomes thin layer

### Phase 4: Docker Compose
```yaml
services:
  engine:
    build: .
    command: python -m workspace_secretary.engine
    volumes:
      - ./config:/app/config
      - engine-socket:/tmp
    restart: unless-stopped

  mcp:
    build: .
    command: python -m workspace_secretary
    volumes:
      - ./config:/app/config:ro
      - engine-socket:/tmp:ro
    ports:
      - "8000:8000"
    depends_on:
      - engine

volumes:
  engine-socket:
```

## Migration Path

1. v2.x users: Single-process continues to work (backward compatible)
2. v3.0: Dual-process available as opt-in via docker-compose
3. v3.1+: Dual-process becomes default

## File Structure (Post-Refactor)

```
workspace_secretary/
├── __main__.py              # MCP entry point
├── server.py                # MCP server (thin layer)
├── tools.py                 # MCP tools (reads SQLite, calls Engine API)
├── resources.py             # MCP resources
├── engine/
│   ├── __main__.py          # Engine entry point
│   ├── daemon.py            # Main daemon loop
│   ├── api.py               # FastAPI Unix socket server
│   ├── imap_sync.py         # IMAP sync logic
│   ├── calendar_sync.py     # Calendar sync logic
│   ├── email_cache.py       # Email SQLite operations
│   ├── calendar_cache.py    # Calendar SQLite operations
│   └── oauth2.py            # OAuth2 handling
├── config.py                # Shared config
└── models.py                # Shared data models
```

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| IPC mechanism | Unix socket | Secure, no network exposure, fast |
| Repository | Single repo | Shared models, simpler releases |
| Database | SQLite (WAL + FTS5) | Deployment simplicity, sufficient for single-user |
| Calendar sync depth | Full history | Historical data for AI context |
| Backward compat | Yes (v2.x mode) | Existing users not disrupted |
