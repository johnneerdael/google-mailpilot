# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
