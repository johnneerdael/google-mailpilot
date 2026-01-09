# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
