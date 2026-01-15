# Email Threading

Google MailPilot uses Gmail's native threading via the `X-GM-THRID` IMAP extension for accurate, instant conversation grouping.

## Overview

Email threading groups related messages into conversations. This is essential for:

- Understanding email context without reading each message individually
- AI agents summarizing entire conversations
- Identifying the latest response in a thread
- Finding all related messages with a single query

## Gmail Threading with X-GM-THRID

Gmail provides a proprietary IMAP extension that exposes the same thread IDs used in the Gmail web interface and API. This is the **canonical** threading mechanism we use.

### Why X-GM-THRID?

| Approach | Accuracy | Performance | Gmail Support |
|----------|----------|-------------|---------------|
| **X-GM-THRID** (current) | Perfect | Instant | Native ✅ |
| RFC 5256 THREAD | Good | Slow | Supported |
| Local header parsing | Variable | Fast | N/A |

X-GM-THRID advantages:
- **Exact match** with Gmail web UI threading
- **64-bit unique identifier** per thread
- **Server-computed** - no client-side guesswork
- **Instant retrieval** via IMAP FETCH or SEARCH

### How It Works

Gmail's IMAP server exposes thread IDs through the `X-GM-THRID` attribute:

```text
# Fetch thread ID for messages
A001 FETCH 1:4 (X-GM-THRID)
* 1 FETCH (X-GM-THRID 1278455344230334865)
* 2 FETCH (X-GM-THRID 1266894439832287888)
* 3 FETCH (X-GM-THRID 1266894439832287888)
* 4 FETCH (X-GM-THRID 1266894439832287888)
A001 OK FETCH (Success)
```

Messages 2, 3, and 4 share the same thread ID - they're in the same conversation.

### Searching by Thread

Find all messages in a thread using IMAP SEARCH:

```text
A002 UID SEARCH X-GM-THRID 1266894439832287888
* SEARCH 2 3 4
A002 OK SEARCH (Success)
```

This returns UIDs of all messages in the conversation, regardless of folder.

## Data Model

Each email stores Gmail-native identifiers:

| Column | Type | Description |
|--------|------|-------------|
| `gmail_thread_id` | TEXT | X-GM-THRID value (64-bit as string) |
| `gmail_message_id` | TEXT | X-GM-MSGID value (unique per message) |
| `gmail_labels` | TEXT | X-GM-LABELS (comma-separated) |

### Database Schema

```sql
CREATE TABLE emails (
    -- ... other columns ...
    gmail_thread_id TEXT,
    gmail_message_id TEXT,
    gmail_labels TEXT
);

CREATE INDEX idx_gmail_thread_id ON emails(gmail_thread_id);
```

Thread lookups are O(1) index scans.

## Using Thread Tools

### get_email_thread

Retrieves all emails in a conversation by thread ID:

```json
{
  "tool": "get_email_thread",
  "arguments": {
    "thread_id": "1266894439832287888"
  }
}
```

Returns all emails sharing that `gmail_thread_id`, sorted by date.

### gmail_get_thread

Alternative using any email's UID to discover thread:

```json
{
  "tool": "gmail_get_thread",
  "arguments": {
    "uid": 12345,
    "folder": "INBOX"
  }
}
```

Looks up the email's thread ID, then returns all related messages.

### summarize_thread

Gets thread content optimized for AI summarization:

```json
{
  "tool": "summarize_thread",
  "arguments": {
    "thread_id": "1266894439832287888"
  }
}
```

Returns:
- Participant list
- Message count
- Full content (truncated to 2000 chars per message)
- Chronological ordering

## Performance

Thread operations are instant thanks to indexed lookups:

| Operation | Time | Method |
|-----------|------|--------|
| Get thread (any size) | < 10ms | Index scan on gmail_thread_id |
| Find all threads from sender | < 50ms | Compound index |
| Summarize 20-message thread | < 100ms | Single query + formatting |

### Comparison with RFC 5256

The legacy RFC 5256 `THREAD` command required:
1. Server-side computation per query
2. Multiple round-trips for large threads
3. Re-computation on every request

With X-GM-THRID:
1. Thread ID fetched once during sync
2. Stored permanently in database
3. All subsequent lookups are local

## Other Gmail IMAP Extensions

We leverage additional Gmail extensions:

### X-GM-MSGID

Unique message identifier (survives moves between folders):

```text
A003 FETCH 1 (X-GM-MSGID)
* 1 FETCH (X-GM-MSGID 1278455344230334866)
```

### X-GM-LABELS

Gmail labels applied to the message:

```text
A004 FETCH 1 (X-GM-LABELS)
* 1 FETCH (X-GM-LABELS ("\\Important" "\\Starred" "Work" "Project-X"))
```

Labels are synced and stored, enabling queries like "all starred emails" without IMAP round-trips.

## Migration from v2.x

::: warning Deprecated: RFC 5256 Threading
Versions before v4.0 used RFC 5256 `THREAD REFERENCES` with local fallback. This has been **deprecated** in favor of X-GM-THRID.

Old columns (`thread_root_uid`, `thread_parent_uid`, `thread_depth`) are no longer used. The `gmail_thread_id` column is the source of truth.
:::

### Automatic Migration

On upgrade, the sync engine:
1. Fetches `X-GM-THRID` for all existing emails
2. Populates `gmail_thread_id` column
3. Rebuilds thread index

This happens automatically during the first sync cycle.

## Troubleshooting

### Thread Missing Some Messages

Messages in Trash or Spam may not appear. Check:
```bash
# Search across all folders
docker exec workspace-secretary sqlite3 /app/config/email_cache.db \
  "SELECT folder, uid, subject FROM emails WHERE gmail_thread_id = '1266894439832287888';"
```

### Thread ID is NULL

Older synced emails may lack thread IDs. Force a re-sync:
```bash
docker compose restart workspace-secretary
```

The sync engine backfills missing Gmail attributes.

### Non-Gmail Servers

X-GM-THRID is Gmail-specific. For other IMAP servers:
- RFC 5256 THREAD support varies
- Local threading via `In-Reply-To`/`References` headers is available
- Contact us for enterprise multi-provider support

## Technical References

- [Gmail IMAP Extensions](https://developers.google.com/gmail/imap/imap-extensions)
- [X-GM-THRID Documentation](https://developers.google.com/gmail/imap/imap-extensions#access_to_the_gmail_thread_id_x-gm-thrid)
- [X-GM-MSGID Documentation](https://developers.google.com/gmail/imap/imap-extensions#access_to_the_gmail_unique_message_id_x-gm-msgid)
- [X-GM-LABELS Documentation](https://developers.google.com/gmail/imap/imap-extensions#access_to_gmail_labels_x-gm-labels)
