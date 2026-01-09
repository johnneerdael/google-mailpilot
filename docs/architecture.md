# Architecture: Local-First Email Client with MCP Interface

## Overview

Version 2.0.0 introduces a fundamental architectural change: the Google Workspace Secretary is now a **local-first IMAP email client** with an MCP (Model Context Protocol) interface.

This is the same architecture used by desktop email clients like Thunderbird and Apple Mail:

1. **Initial Sync**: Download all email metadata and bodies to local storage
2. **Local Queries**: All searches and filters run against the local database (instant)
3. **Incremental Updates**: Only fetch new/changed emails from the server
4. **Mutations**: Write operations go to IMAP, then immediately update local cache

The difference: instead of a GUI, the interface is MCP—enabling AI agents to interact with your email.

```
┌─────────────────────────────────────────────────────────────┐
│                    Container Startup                         │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              ClientManager.initialize()                      │
│         IMAP Connect + Background Sync Thread                │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│     Full Sync (first run) or Incremental Sync (subsequent)   │
│              SQLite ← IMAP Server                            │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   MCP Tools Available                        │
│    Reads → SQLite (instant)    Writes → IMAP + SQLite       │
└─────────────────────────────────────────────────────────────┘
```

## SQLite Cache Architecture

### Database Location

```
config/email_cache.db
```

This path maps to `/app/config/email_cache.db` inside the Docker container. The `./config:/app/config` volume mount ensures persistence across container restarts.

### Schema

#### `emails` Table

Stores complete email data including full message bodies:

```sql
CREATE TABLE emails (
    uid INTEGER NOT NULL,           -- IMAP UID (unique within folder)
    folder TEXT NOT NULL,           -- Folder name (e.g., "INBOX")
    message_id TEXT,                -- RFC 2822 Message-ID header
    subject TEXT,                   -- Email subject
    from_addr TEXT,                 -- Sender (formatted: "Name <email>")
    to_addr TEXT,                   -- Recipients (comma-separated)
    cc_addr TEXT,                   -- CC recipients (comma-separated)
    date TEXT,                      -- ISO 8601 timestamp
    body_text TEXT,                 -- Plain text body (complete)
    body_html TEXT,                 -- HTML body (complete)
    flags TEXT,                     -- IMAP flags (comma-separated)
    is_unread BOOLEAN,              -- Derived from \Seen flag
    is_important BOOLEAN,           -- Derived from \Flagged flag
    size INTEGER,                   -- Approximate message size
    modseq INTEGER,                 -- CONDSTORE modification sequence
    synced_at TEXT,                 -- Last sync timestamp
    PRIMARY KEY (uid, folder)
);
```

#### `folder_state` Table

Tracks IMAP folder state for incremental synchronization:

```sql
CREATE TABLE folder_state (
    folder TEXT PRIMARY KEY,        -- Folder name
    uidvalidity INTEGER,            -- IMAP UIDVALIDITY value
    uidnext INTEGER,                -- Next expected UID
    highestmodseq INTEGER,          -- Highest MODSEQ seen
    last_sync TEXT                  -- Last sync timestamp
);
```

### Indexes

```sql
CREATE INDEX idx_folder ON emails(folder);
CREATE INDEX idx_unread ON emails(is_unread);
CREATE INDEX idx_date ON emails(date);
CREATE INDEX idx_from ON emails(from_addr);
CREATE INDEX idx_message_id ON emails(message_id);
CREATE INDEX idx_modseq ON emails(modseq);
```

## IMAP Sync Protocol

The sync implementation follows best practices from IMAP RFCs:

- **RFC 3501**: IMAP4rev1 base protocol
- **RFC 4549**: Synchronization Operations for Disconnected IMAP4 Clients
- **RFC 5162**: IMAP4 Extensions for Quick Mailbox Resynchronization (QRESYNC)

### UIDVALIDITY

Every IMAP folder has a `UIDVALIDITY` value—a unique identifier that changes whenever UIDs are reassigned (e.g., after folder repair or server migration).

**Rule**: If `UIDVALIDITY` changes, the entire local cache for that folder is invalid and must be cleared.

```python
if stored_state.get("uidvalidity") != current_uidvalidity:
    logger.warning("UIDVALIDITY changed, cache invalidated - full sync required")
    self.clear_folder(folder)
    need_full_sync = True
```

### UIDNEXT

`UIDNEXT` is the next UID the server will assign. By storing this value, we know exactly which emails are new:

```python
# Only fetch emails with UID > last known UIDNEXT
new_uids = client.search({"UID": f"{last_uid + 1}:*"}, folder=folder)
```

### Full Sync vs Incremental Sync

| Trigger | Sync Type | What Happens |
|---------|-----------|--------------|
| No `folder_state` record | Full | Download all emails |
| `UIDVALIDITY` changed | Full | Clear cache, download all emails |
| `UIDVALIDITY` unchanged | Incremental | Only fetch UIDs > stored `uidnext` |

### Batch Processing

To avoid memory issues and provide progress feedback, emails are fetched in batches:

```python
batch_size = 50

for batch_start in range(0, total, batch_size):
    batch_uids = uid_list[batch_start : batch_start + batch_size]
    emails = client.fetch_emails(batch_uids, folder=folder)
    # Process and commit batch
    conn.commit()
    # Save folder state after each batch (crash recovery)
    self._save_folder_state(folder, uidvalidity, highest_uid_in_batch + 1)
```

### Deletion Detection

During incremental sync, we detect emails deleted on the server:

```python
def _sync_deletions(self, client, folder):
    server_uids = set(client.search({"ALL": True}, folder=folder))
    cached_uids = {row[0] for row in conn.execute("SELECT uid FROM emails WHERE folder = ?")}
    
    deleted_uids = cached_uids - server_uids
    if deleted_uids:
        conn.execute(f"DELETE FROM emails WHERE folder = ? AND uid IN ({placeholders})")
```

## Startup Behavior

### Initialization Sequence

1. **Container starts** → Python process begins
2. **`ClientManager.initialize()`** → Loads config, connects to IMAP
3. **Background sync thread** → Spawns immediately (daemon thread)
4. **MCP server ready** → Accepts connections while sync runs

```python
class ClientManager:
    def initialize(self, config_path):
        self.imap_client.connect()
        self._initialized = True
        self._start_background_sync()  # Non-blocking
```

### Sync Timeline

| Mailbox Size | Initial Sync Time | Incremental Sync |
|--------------|-------------------|------------------|
| 1,000 emails | ~1-2 minutes | Seconds |
| 10,000 emails | ~10-15 minutes | Seconds |
| 25,000 emails | ~25-30 minutes | Seconds |

### Crash Recovery

Folder state is saved after each batch. If the container restarts mid-sync:

1. On startup, `folder_state` is read
2. Sync resumes from `uidnext` (last successfully synced UID + 1)
3. Already-cached emails are not re-downloaded

### Periodic Sync

After initial sync completes, incremental sync runs every 5 minutes:

```python
while True:
    time.sleep(300)  # 5 minutes
    self._run_sync()
```

## Cache Invalidation

All mutation tools follow this pattern:

```
1. Execute IMAP operation
2. If successful, update SQLite cache
3. Return result to caller
```

### Tools with Cache Invalidation

| Tool | IMAP Operation | Cache Update |
|------|----------------|--------------|
| `mark_as_read` | Add `\Seen` flag | `UPDATE emails SET is_unread = 0` |
| `mark_as_unread` | Remove `\Seen` flag | `UPDATE emails SET is_unread = 1` |
| `move_email` | COPY + DELETE | `UPDATE emails SET folder = ?` |
| `process_email` | Various | Corresponding cache update |
| `quick_clean_inbox` | Bulk MOVE | Bulk cache updates |

### Example: mark_as_read

```python
async def mark_as_read(folder, uid, ctx):
    client = get_client_from_context(ctx)
    client.mark_email(uid, folder, r"\Seen", True)  # IMAP
    
    cache = get_email_cache_from_context(ctx)
    if cache:
        cache.mark_as_read(uid, folder)  # SQLite
    
    return "Email marked as read"
```

## Performance Characteristics

### Read Operations (SQLite)

| Operation | Time |
|-----------|------|
| `get_unread_messages` | < 10ms |
| `search_emails` | < 50ms |
| `quick_clean_inbox` filtering | < 100ms |

### Write Operations (IMAP + SQLite)

| Operation | Time |
|-----------|------|
| `mark_as_read` | 100-500ms |
| `move_email` | 200-800ms |
| `send_email` | 500ms-2s |

### Sync Performance

| Operation | Rate |
|-----------|------|
| Batch fetch | ~50 emails / 2-3 seconds |
| Incremental sync (no changes) | < 1 second |
| Deletion detection | ~1 second per 10,000 cached emails |

## Docker Volume Requirements

### Required Mount

```yaml
volumes:
  - ./config:/app/config
```

This mount is **required** for:

1. **Cache persistence**: `email_cache.db` survives container restarts
2. **Credential storage**: OAuth tokens and config
3. **Task storage**: `tasks.json` for task management

### Without Volume Mount

If the volume is not mounted:

- Full sync runs on every container restart
- OAuth tokens are lost (re-authentication required)
- All cached emails are lost

### Database Size

Approximate storage requirements:

| Emails | Database Size |
|--------|---------------|
| 1,000 | ~10-20 MB |
| 10,000 | ~100-200 MB |
| 25,000 | ~250-500 MB |

Size varies based on email content (attachments are not cached, only body text/HTML).
