# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.2.7] - 2026-01-10

### Fixed

- **Gap Sync via Set Difference**: Finds missing UIDs by comparing IMAP vs DB
  - Queries all IMAP UIDs and all synced DB UIDs
  - Computes set difference to find exactly what's missing
  - Fixes gap sync when emails were synced oldest-first then newest-first
- **Accurate Progress Counters**: Uses actual DB counts instead of cursor-based estimation
  - `count_emails()` and `get_synced_uids()` added to database interface
  - Progress shows real state: "15506/24230 done, 8724 remaining"

## [4.2.6] - 2026-01-10

### Fixed

- **Resume Sync on Restart**: Sync now resumes from stored `uidnext` instead of starting over
  - Shows accurate progress: "Resuming (16000/26000 done, 10000 remaining)"
  - Skips folders that are already fully synced
- **IDLE Starts Immediately**: No longer waits for initial sync to complete
  - IDLE runs in dedicated thread, independent from sync executor
  - New emails detected in real-time even during initial sync
- **Empty Text Filtering for Embeddings**: Prevents 400 Bad Request errors
  - Requires minimum 3 characters and at least one alphanumeric character
  - Skips emails with empty/invalid body content
  - Better error logging with response body on API errors

## [4.2.5] - 2026-01-10

### Changed

- **Lockstep Sync+Embed Architecture**: Complete rewrite of sync/embedding coordination
  - Sync and embed now run in lockstep: sync 50 emails → embed those 50 → repeat
  - Eliminates race condition where embeddings could process more emails than synced
  - IDLE monitor and embeddings loop only start after initial sync completes
  - Fixes "2200/2000 embeddings processed" bug caused by concurrent DB writes

### Fixed

- **Event Loop Blocking in Pool Init**: `_init_connection_pool()` now runs in executor
  - Added `asyncio.Lock` to prevent race condition on pool initialization
- **Oldest-First Sync Order**: Now syncs emails from oldest to newest UID
  - Previously synced newest-first then skipped all older emails
  - Uses cursor-based pagination to process all emails (e.g., all 26000 instead of just 50)
- **httpx Client Reuse**: `EmbeddingsClient` now reuses single `AsyncClient` instance
  - Added `Semaphore(4)` to limit concurrent embedding requests
  - Prevents connection exhaustion and reduces overhead

## [4.2.4] - 2026-01-10

### Added

- **Parallel Folder Sync**: Sync multiple folders simultaneously using IMAP connection pool
  - Up to 5 concurrent connections (configurable via `MAX_SYNC_CONNECTIONS`)
  - Each folder syncs on its own connection from the pool
  - Initial sync completes much faster for accounts with multiple folders

### Changed

- **Sync Strategy Overhaul**: Replaced fixed-interval polling with IDLE + catch-up
  - Initial sync: parallel sync all folders at startup
  - Real-time: IDLE push notifications for INBOX (dedicated thread)
  - Catch-up: periodic sync every 30 min (configurable via `SYNC_CATCHUP_INTERVAL`)
  - Removed old 5-minute polling interval

### Fixed

- **Connection Pool Lifecycle**: Proper shutdown of sync connections on engine stop

## [4.2.3] - 2026-01-10

### Fixed

- **IDLE Event Loop Blocking**: IMAP IDLE operations now run on a dedicated thread
  - `select_folder`, `idle_start`, `idle_check`, `idle_done` were blocking the asyncio event loop for up to 25 minutes
  - Sync loop would hang immediately after startup, never executing the main sync
  - New `_idle_worker()` runs entire IDLE loop on separate thread with clean shutdown coordination
  - Uses `loop.call_soon_threadsafe()` to schedule syncs back to the event loop
  - `sync_emails()` now wrapped in `run_in_executor` to avoid blocking

## [4.2.2] - 2026-01-10

### Fixed

- **Database Initialization**: Engine now calls `database.initialize()` after `create_database()`
  - Fixes "Database not initialized. Call initialize() first" error during sync
- **PostgreSQL Dependencies**: Docker image now includes `psycopg[binary]` and `psycopg-pool`
  - Added `postgres` optional dependency group in pyproject.toml
  - Dockerfile uses `--extra postgres` to install PostgreSQL drivers

### Added

- **Sync Logging**: INFO-level logs for sync operations
  - "Synced N new emails from FOLDER" on new email inserts
  - "Updated flags for N emails in FOLDER" on CONDSTORE flag changes

### Documentation

- **OAuth Setup Simplified**: Removed outdated `--token-output` and `--config` flags from examples
  - Token always saves to `/app/config/token.json` (hardcoded)
  - Config always at `/app/config/config.yaml`
- **Docker Guide Overhauled**: Added PostgreSQL setup, fixed OAuth examples
- **Threading Docs Updated**: Deprecated RFC 5256 threading in favor of Gmail's X-GM-THRID extension
- **Architecture Deep Dive**: Added comprehensive IMAP client section covering CONDSTORE, IDLE, Gmail extensions
- **Renamed /api/ to /tools/**: Better reflects MCP tool documentation

## [4.2.1] - 2026-01-09

### Fixed

- **OAuth Token Storage**: `auth_setup` now saves `client_id` and `client_secret` in `token.json`
  - Previously only saved access/refresh tokens, causing "Missing client_id or client_secret" error
  - Engine can now refresh tokens properly after initial OAuth flow

### Changed

- **Improved Setup UX**: Startup warning now shows both authentication options
  - Option 1: OAuth2 via `auth_setup` (recommended)
  - Option 2: App Password via `app_password`
- **Hardcoded Config Paths**: Removed user-configurable output paths to prevent misconfiguration
  - `auth_setup`: Token always saves to `/app/config/token.json`
  - `app_password`: Config always saves to `/app/config/config.yaml`

### DevOps

- **Docs Workflow**: GitHub Actions now builds documentation on tag push (not just main branch)
  - Version in docs automatically updated on release

## [4.2.0] - 2026-01-09

### Changed

- **Calendar API Passthrough**: Calendar operations now go directly to Google Calendar API
  - Removed local calendar database caching
  - All calendar queries are real-time against Google API
  - Simpler architecture, no sync staleness issues

### Added

- **New Calendar API Endpoints**:
  - `GET /api/calendar/list` - List all user's calendars
  - `GET /api/calendar/{calendar_id}` - Get calendar details
  - `GET /api/calendar/{calendar_id}/events/{event_id}` - Get single event
  - `PATCH /api/calendar/{calendar_id}/events/{event_id}` - Update event
  - `DELETE /api/calendar/{calendar_id}/events/{event_id}` - Delete event
  - `POST /api/calendar/freebusy` - Query free/busy for multiple calendars

### Removed

- `calendar_cache.py` - Calendar caching layer removed
- `gmail_client.py` - Deprecated Gmail REST API client removed
- `CalendarSync` class - No longer needed without caching
- Calendar database tables (calendars, events, attendees)
- `calendar_cache_path` config option (ignored if present)

### Migration

- **Automatic**: No action required
- Calendar operations work immediately without sync delay
- Existing `calendar_cache_path` in config is ignored (not an error)

## [4.1.2] - 2026-01-09

### Changed

- **README Rewrite**: Complete documentation overhaul focusing on technical depth
  - Repositioned as "Gmail IMAP/SMTP Client for AI Agents" (not just MCP wrapper)
  - Added RFC compliance section (IMAP4rev1, CONDSTORE, IDLE, CHANGEDSINCE)
  - Added Gmail extensions documentation (X-GM-THRID, X-GM-MSGID, X-GM-LABELS, X-GM-RAW)
  - Added performance benchmarks and CONDSTORE sync explanation
  - Added architecture diagram showing dual-process design
  - Added signal extraction and HITL safety documentation
  - Added database schema documentation

## [4.1.1] - 2026-01-09

### Fixed

- **Config Path Resolution**: Engine now correctly finds `config.yaml` in Docker environments
  - Previously used relative `config.yaml` path which failed when working directory was `/app`
  - Now uses `load_config()` search paths including `/app/config/config.yaml`
  - Fixes "No configuration file found" error in Docker deployments

## [4.1.0] - 2026-01-09

### Added

- **CONDSTORE Support (RFC 7162)**: Efficient incremental sync using HIGHESTMODSEQ
  - Skip sync entirely when mailbox unchanged (HIGHESTMODSEQ comparison)
  - `fetch_changed_since()` for flag-only updates via CHANGEDSINCE modifier
  - Dramatically reduces sync overhead for active mailboxes
- **IMAP IDLE Support (RFC 2177)**: Push-based sync notifications
  - Dedicated IDLE connection monitors INBOX for changes
  - `idle_monitor()` background task triggers immediate sync on new mail
  - No more waiting for 5-minute poll interval
- **Gmail Extensions**: Native Gmail protocol support
  - `X-GM-MSGID` and `X-GM-THRID` for message/thread identification
  - `X-GM-LABELS` stored in database (JSONB for PostgreSQL, comma-separated for SQLite)
  - `gmail_raw_search()` internal method for targeted sync optimization
- **Enhanced Email Metadata**:
  - `internal_date` (INTERNALDATE) - server receipt timestamp
  - `size` (RFC822.SIZE) - message size in bytes
  - `modseq` - modification sequence for CONDSTORE
  - `has_attachments` and `attachment_filenames` - extracted from MIME structure
- **Debounced Sync**: Mutations (move, labels, send) trigger 2-second debounced sync
  - Batches rapid changes into single sync operation
  - Immediate feedback without overwhelming the server

### Changed

- **Database Schema**: New columns for Gmail-native features
  - Added: `gmail_thread_id`, `gmail_msgid`, `gmail_labels`, `bcc_addr`, `internal_date`, `has_attachments`, `attachment_filenames`
  - Removed: Legacy `thread_root_uid`, `thread_parent_uid`, `thread_depth` (replaced by `gmail_thread_id`)
  - New `update_email_flags()` method for CONDSTORE flag-only updates
  - `save_folder_state()` now stores `highestmodseq`
- **Sync Engine Rewrite**: CONDSTORE-first with graceful fallback
  - Checks HIGHESTMODSEQ before any fetch operations
  - Uses CHANGEDSINCE for incremental flag sync
  - Falls back to UID-based sync if CONDSTORE unavailable
- **EngineState**: Added `idle_client`, `idle_task`, `_sync_debounce_task` for IDLE support

### Performance

- **Unchanged mailbox**: Skip sync entirely (was: fetch all UIDs, compare)
- **Flag changes only**: Fetch only changed flags (was: re-fetch entire message)
- **New mail detection**: Instant via IDLE (was: 5-minute poll interval)
- **Batch mutations**: Single sync after multiple rapid changes (was: sync per mutation)

## [4.0.0] - 2026-01-09

### ⚠️ BREAKING: Complete Architecture Rewrite

This release fundamentally changes how the system works internally. The Engine now owns **all database writes**, while the MCP server is **read-only** against the database.

### Changed

- **Engine owns all database writes**: Engine now uses `DatabaseInterface` (not legacy `EmailCache`) for all persistence
- **MCP is read-only**: MCP server reads directly from database, calls Engine API only for mutations
- **Unified database access**: Both Engine and MCP use the same `DatabaseInterface` abstraction
- **Database backend selection**: `config.database.backend` determines SQLite or PostgreSQL for both processes

### Added

- **New Engine API endpoints**:
  - `GET /api/calendar/events` - List calendar events in time range
  - `GET /api/calendar/availability` - Get free/busy information
  - `POST /api/email/setup-labels` - Create Secretary label hierarchy in Gmail
  - `POST /api/email/send` - Send email via Gmail API
  - `POST /api/email/draft-reply` - Create draft reply to an email
- **Calendar sync in Engine**: `sync_loop()` now syncs both email and calendar
- **Automatic embedding generation**: Engine generates embeddings after email sync (PostgreSQL + pgvector)
- **Graceful enrollment**: Engine starts in "no account" mode and auto-connects when OAuth tokens appear

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MCP Server    │────▶│  SQLite/PG DB   │◀────│     Engine      │
│  (read-only)    │     │  (unified)      │     │  (all writes)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                                               │
        └──────────────▶ Engine FastAPI ◀───────────────┘
                        (mutations only)
```

### Migration

- **Automatic**: Existing SQLite caches are compatible
- **No action required**: Config format unchanged

## [3.2.0] - 2026-01-09

### Changed
- **Docker-First Config Discovery**: `/app/config/config.yaml` is now the first default location checked
- **Consolidated OAuth**: All OAuth logic merged into `auth_setup.py` with modern v2 endpoint
  - Supports `--manual` (default) and `--browser` modes
  - `--token-output` flag for Docker-friendly token management
  - Gmail + Calendar scopes included by default

### Removed
- `browser_auth.py` — functionality merged into `auth_setup.py`
- `gmail_auth.py` — duplicate entry point removed
- Related test files for removed modules

### Fixed
- Config discovery now works out-of-the-box in Docker without explicit `--config` flag

## [3.1.0] - 2026-01-09

### Changed
- **Single Container Architecture**: Engine + MCP server now run via supervisord in one container
  - Supervisor manages both processes internally
  - Unix socket IPC between engine and MCP server
  - Simplified deployment: one container instead of two
- **Simplified Docker Compose**: Removed multi-container complexity
- **Documentation**: Added `credentials.json` example format in getting-started guide

### Fixed
- Version synchronization across pyproject.toml, __init__.py, and docs

## [3.0.0] - 2026-01-09

### Added
- **Dual-Process Architecture**: Complete separation of engine and MCP server
  - `secretary-engine`: Persistent IMAP connection, background sync daemon
  - `secretary-mcp`: Stateless MCP server exposing tools via HTTP
- **Calendar Sync**: Full calendar synchronization with local SQLite cache
- **Unix Socket IPC**: Engine exposes internal API for mutations
- **Semantic Search**: Optional PostgreSQL + pgvector backend with embeddings
- **Configurable Database**: SQLite (default) or PostgreSQL with pgvector

### Changed
- **Breaking**: Removed `OAuthMode` enum and `oauth_mode` config field - IMAP-only mode
- **Breaking**: Removed `--mode` CLI flags from auth setup tools
- Server always uses IMAP/SMTP protocols (API mode removed)

### Removed
- `API_MODE_SCOPES` and API mode code paths
- `get_oauth_mode_from_context()` helper
- `get_scopes_for_mode()` function
- OAuth mode selection (consolidated into auth_setup.py)

## [2.1.0] - 2026-01-09

### Changed
- **Sync Direction**: Initial sync now processes emails **newest-first** (descending UID order)
  - Recent emails available within seconds of startup
  - Can start using MCP immediately while older emails sync in background
  - No more waiting for full sync to see today's emails

### Documentation
- **Comprehensive v2.0 documentation overhaul**:
  - README.md rewritten with v2.0 architecture, bearer auth best practices, UUID generation
  - config.sample.yaml updated with security recommendations and cache behavior
  - docs/guide/docker.md completely rewritten for SQLite persistence and sync behavior
  - docs/guide/security.md added platform-specific UUID generation (macOS/Linux/Windows/OpenSSL)
  - docs/guide/configuration.md added cache config section
  - docs/architecture.md expanded with sync direction, instant mutation updates, usability during sync
  - VitePress nav updated with Architecture link and v2.1.0 version

### Fixed
- Bearer auth now **strongly recommended** (was optional) with clear UUID generation instructions

## [2.0.0] - 2026-01-09

### Added
- **SQLite Email Cache**: Local-first architecture with full email body storage
  - Complete email bodies (text and HTML) cached locally
  - Instant queries against SQLite instead of IMAP round-trips
  - Database persisted at `config/email_cache.db`
- **IMAP Sync Engine**: Proper email client synchronization
  - UIDVALIDITY tracking for cache invalidation
  - UIDNEXT-based incremental sync (only fetches new emails)
  - Batch processing (50 emails/batch) with progress logging
  - Deletion detection during sync
  - Automatic sync on container startup (no MCP request required)
  - Periodic incremental sync every 5 minutes
- **Crash Recovery**: Folder state saved after each batch
  - Interrupted syncs resume from last checkpoint
  - No duplicate downloads on container restart
- **Architecture Documentation**: New `docs/architecture.md` explaining:
  - SQLite schema and indexes
  - IMAP sync protocol (RFC 3501, RFC 4549, RFC 5162)
  - Cache invalidation strategy
  - Performance characteristics

### Changed
- **Breaking**: Server now initializes IMAP connection on startup, not lazily on first request
- `get_unread_messages` now queries SQLite cache (instant) with IMAP fallback
- All mutation tools (`mark_as_read`, `mark_as_unread`, `move_email`, `process_email`, `quick_clean_inbox`) now immediately update SQLite cache after IMAP operation
- `ClientManager` class manages global IMAP connection and background sync thread

### Performance
- Read operations: < 10ms (was 30-60 seconds via IMAP)
- Initial sync: ~2-3 seconds per 50 emails
- Incremental sync: Seconds (only new emails)
- Mailbox with 26,000 emails: ~25-30 minute initial sync, then instant queries

## [1.2.1] - 2026-01-09

### Fixed
- Multi-architecture Docker builds now support both `linux/amd64` and `linux/arm64`
- Container registry URL corrected to `ghcr.io/johnneerdael/google-workspace-secretary-mcp`

### Added
- Manual OAuth flow (`--manual` flag) for Docker and headless environments
- Docker-based authentication documentation in oauth_workaround.md
- Redirect URI reference table for third-party OAuth providers

## [1.2.0] - 2026-01-08

### Added
- **Email Triage Tools**:
  - `quick_clean_inbox` - Auto-clean emails where user is not addressed (no confirmation required)
  - `triage_priority_emails` - Identify high-priority emails based on recipient count and name mentions
  - `triage_remaining_emails` - Process remaining emails after priority triage
- **User Identity Configuration**:
  - New `identity` section in config.yaml with `email`, `full_name`, and `aliases`
  - Automatic name parsing (first_name, last_name) from full_name
  - Methods for matching emails and name variations
- **New Email Signals**:
  - `is_addressed_to_me` - User's email in To: field
  - `mentions_my_name` - User's name mentioned in email body
- **OpenCode Slash Commands**:
  - `/clean-inbox` - Invoke quick_clean_inbox
  - `/triage-priority` - Invoke triage_priority_emails
  - `/triage-remaining` - Invoke triage_remaining_emails

### Changed
- `get_daily_briefing` now includes `is_addressed_to_me` and `mentions_my_name` signals
- AGENTS.md updated with triage tool documentation and confidence-based approval rules

## [1.1.0] - 2026-01-07

### Added
- Gmail-native search with `gmail_search` tool
- Smart labels system (`Secretary/Priority`, `Secretary/Action-Required`, etc.)
- Calendar integration with timezone-aware scheduling
- Document intelligence for PDF/DOCX attachments
- VIP sender configuration
- Working hours and workdays configuration

## [1.0.0] - 2026-01-05

### Added
- Initial release
- IMAP email access with OAuth2 authentication
- Basic email search and retrieval
- Thread summarization
- Draft creation (safe, non-sending)
- MCP server with Streamable HTTP transport
