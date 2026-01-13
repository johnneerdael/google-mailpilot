# Architecture v4.8.0

This document describes the Gmail Secretary architecture including the 3-process deployment model, sync engine implementation, IMAP connection pooling, and the IDLE threading model.

## Deployment Architecture (v4.8.0+)

Gmail Secretary runs as three coordinated processes managed by supervisord:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Docker Container (supervisord)                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐    │
│  │  Engine API      │   │  MCP Server      │   │  Web UI          │    │
│  │  Port: 8001      │   │  Port: 8000      │   │  Port: 8080      │    │
│  │  (internal only) │   │  (exposed)       │   │  (exposed)       │    │
│  ├──────────────────┤   ├──────────────────┤   ├──────────────────┤    │
│  │ • IMAP sync      │◄──│ • Tool exposure  │   │ • Human UI       │    │
│  │ • IDLE monitor   │   │ • Read from DB   │   │ • Dashboard      │    │
│  │ • Mutations      │◄──┤ • Proxy writes   │◄──┤ • Settings       │    │
│  │ • DB writes      │   │   to Engine      │   │ • AI chat        │    │
│  │ • OAuth mgmt     │   │ • Bearer auth    │   └──────────────────┘    │
│  └──────────────────┘   └──────────────────┘                            │
│         │                                                                │
│         ▼                                                                │
│  ┌──────────────────────────────────────────┐                           │
│  │  SQLite / PostgreSQL Database            │                           │
│  │  • Email cache (FTS5)                    │                           │
│  │  • Gmail labels (JSONB)                  │                           │
│  │  • Embeddings (pgvector)                 │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │   Gmail IMAP/SMTP    │
                    │   Google Calendar    │
                    └──────────────────────┘
```

### Process Responsibilities

| Process | Port | Exposed | Purpose |
|---------|------|---------|---------|
| **Engine API** | 8001 | No (internal) | Handles all mutations, IMAP sync, OAuth token management |
| **MCP Server** | 8000 | Yes | Exposes tools to AI clients (Claude, etc.) |
| **Web UI** | 8080 | Yes | Human web interface for email management |

### Communication Flow

```
AI Client → MCP Server (8000) → Engine API (127.0.0.1:8001) → Gmail IMAP
User Browser → Web UI (8080) → Engine API (127.0.0.1:8001) → Gmail IMAP
```

### Environment Variables

The `ENGINE_API_URL` environment variable configures how MCP Server and Web UI communicate with the Engine:

```yaml
environment:
  - ENGINE_API_URL=http://127.0.0.1:8001  # Default
```

**When to override**: Multi-container deployments where the engine runs on a separate host.

### Why Three Processes?

| Concern | Engine API | MCP Server | Web UI |
|---------|------------|------------|--------|
| **IMAP Connection** | Owns connection, IDLE loop | Never touches IMAP | Never touches IMAP |
| **Database Writes** | All writes happen here | Read-only | Read-only |
| **OAuth Tokens** | Manages tokens, refresh | Stateless | Stateless |
| **Uptime** | Always running | Scales with AI requests | Always running |
| **Scalability** | Single instance (IMAP limit) | Can scale horizontally | Can scale horizontally |

### supervisord Configuration

```ini
[program:engine]
command=uv run python -m workspace_secretary.engine --host 127.0.0.1 --port 8001
autostart=true
autorestart=true

[program:mcp-server]
command=uv run python -m workspace_secretary.server
autostart=true
autorestart=true

[program:web-ui]
command=uv run python -m workspace_secretary.web.main
autostart=true
autorestart=true
```

## Database Layer Architecture (v4.8.0+)

The database layer is organized into modular query modules for maintainability and testability:

```
workspace_secretary/
├── db/
│   ├── types.py              # DatabaseInterface protocol
│   ├── schema.py             # DDL (CREATE TABLE, indexes)
│   ├── postgres.py           # Connection pooling base class
│   └── queries/              # Shared SQL query modules
│       ├── emails.py         # 22 email operations
│       ├── embeddings.py     # 6 semantic search functions
│       ├── contacts.py       # 12 contact functions
│       ├── calendar.py       # 10 calendar functions
│       ├── preferences.py    # 2 user preference functions
│       └── mutations.py      # 4 mutation journal functions
├── engine/
│   └── database.py           # Delegates to db/queries
└── web/
    └── database.py           # Delegates to db/queries (read-only)
```

### Design Principles

- **Single Source of Truth**: All SQL queries live in `db/queries/` modules
- **Pure Functions**: Query functions accept `DatabaseInterface` and return data
- **No Duplication**: Engine and web both use the same query modules
- **Better Testing**: Query functions can be tested independently
- **Clear Boundaries**: Engine keeps self-healing logic, queries stay pure

## Sync Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         asyncio event loop                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  sync_loop()              idle_monitor()           embeddings_loop()     │
│  ───────────              ─────────────            ─────────────────     │
│  1. Initial parallel      Manages thread           Background vector     │
│     sync (all folders)    lifecycle only           generation            │
│  2. Sleep 30 min                                                         │
│  3. Catch-up sync         ┌─────────────┐                                │
│  4. Repeat                │ IDLE Thread │                                │
│         │                 │ ─────────── │                                │
│         │                 │ select_folder                                │
│         ▼                 │ idle_start   │                               │
│  ┌─────────────────┐      │ idle_check   │──► loop.call_soon_threadsafe  │
│  │ ThreadPoolExecutor     │ idle_done    │         │                     │
│  │ (5 workers)     │      └──────────────┘         ▼                     │
│  │                 │                         debounced_sync()            │
│  │ ┌─────────────┐ │                               │                     │
│  │ │ IMAP Pool   │ │                               ▼                     │
│  │ │ Queue(5)    │ │◄────────────────────── sync_emails_parallel()       │
│  │ └─────────────┘ │                                                     │
│  └─────────────────┘                                                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Connection Architecture

| Connection | Purpose | Thread | Lifecycle |
|------------|---------|--------|-----------|
| `idle_client` | IMAP IDLE for INBOX push | Dedicated `idle-worker` thread | Startup → shutdown |
| Connection Pool (1-5) | Parallel folder sync | `ThreadPoolExecutor` workers | On-demand, pooled |

## Sync Strategy

### Phase 1: Initial Sync (Startup)

All configured folders sync in parallel using the connection pool:

```
Folders: [INBOX, Sent, Drafts, [Gmail]/All Mail]
Pool:    [conn1, conn2, conn3, conn4, conn5]

conn1 → INBOX
conn2 → Sent
conn3 → Drafts
conn4 → [Gmail]/All Mail
conn5 → (idle in pool)
```

### Phase 2: Real-time Updates (IDLE)

INBOX monitored via IMAP IDLE on dedicated thread:
- `EXISTS` → new email arrived
- `EXPUNGE` → email deleted
- Triggers `debounced_sync()` via `loop.call_soon_threadsafe()`

### Phase 3: Catch-up Sync (Periodic)

Every 30 minutes (configurable), parallel sync runs again to:
- Sync non-INBOX folders (Sent, Drafts, labels)
- Catch missed IDLE notifications (connection drops)
- Update flags via CONDSTORE/HIGHESTMODSEQ

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MAX_SYNC_CONNECTIONS` | 5 | Size of IMAP connection pool |
| `SYNC_CATCHUP_INTERVAL` | 1800 | Catch-up sync interval in seconds (30 min) |

## Why This Architecture?

### Problem: IMAP Blocking Calls

IMAP operations (`select_folder`, `idle_check`, `fetch`) are blocking. Running them on the asyncio event loop freezes all async tasks.

### Solution: Dedicated Threads

1. **IDLE Thread**: Runs entire IDLE loop (`select_folder` → `idle_start` → `idle_check` → `idle_done`) on a dedicated thread. Communicates back via `loop.call_soon_threadsafe()`.

2. **Sync Thread Pool**: `ThreadPoolExecutor` with pooled IMAP connections. Each folder sync runs in its own worker thread. `asyncio.gather()` coordinates parallel execution.

### Result

- Event loop never blocks
- Up to 5 folders sync simultaneously
- IDLE provides instant INBOX updates
- Catch-up sync handles edge cases

## Gmail Connection Limits

Gmail allows up to 15 simultaneous IMAP connections per account. This architecture uses:
- 1 connection for IDLE
- Up to 5 connections for sync pool
- Total: 6 connections (well under limit)
