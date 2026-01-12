# Calendar Integration

Workspace Secretary provides a powerful offline-first calendar integration with Google Calendar, featuring intelligent caching, background synchronization, and seamless offline operation.

## Overview

The calendar system is built around three core principles:

1. **Cache-First**: All reads happen from local database, eliminating API latency
2. **Offline-Friendly**: Create/edit/delete events without internet connection
3. **Transparent Sync**: Background worker handles synchronization automatically

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User/LLM                              │
└────────────────┬────────────────────────────────────────────┘
                 │ Read: ~50ms
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Engine API                                                  │
│  • GET /api/calendar/events → calendar_events_cache         │
│  • POST /api/calendar/event → calendar_outbox (pending)     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Database (PostgreSQL/SQLite)                                │
│  • calendar_events_cache: Local event storage               │
│  • calendar_outbox: Pending operations queue                │
│  • calendar_sync_state: Sync tokens & health                │
└─────────────────────────────────────────────────────────────┘
                 ▲
                 │ Sync every 60s
                 │
┌────────────────┴────────────────────────────────────────────┐
│  Calendar Worker (Background Process)                        │
│  • Flush outbox → Google Calendar API                       │
│  • Incremental sync using sync tokens                       │
│  • Full sync every 24 hours                                 │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Enable Calendar Sync

In `config/config.yaml`:

```yaml
calendar:
  enabled: true
  verified_client: "your-client-id@apps.googleusercontent.com"
```

The calendar worker uses OAuth2 credentials from the IMAP configuration:

```yaml
imap:
  oauth2:
    enabled: true
    credentials_file: "config/gmail-credentials.json"
    token_file: "config/gmail-token.json"
```

### Worker Configuration

The calendar worker is automatically started by supervisord. Default settings:

- **Sync Interval**: 60 seconds (incremental sync)
- **Full Sync**: Every 24 hours
- **Time Window**: -30 days to +90 days
- **Priority**: 40 (starts after engine/web)

To adjust the time window, modify `workspace_secretary/engine/calendar_worker.py`:

```python
self.window_days_past = 30    # Days in the past
self.window_days_future = 90  # Days in the future
```

## Features

### Instant Calendar Queries

All calendar reads happen from the local cache:

```python
# MCP Tool usage (for LLMs)
events = await list_calendar_events(
    time_min="2026-01-12T00:00:00Z",
    time_max="2026-01-19T23:59:59Z"
)
# Returns instantly from cache (~50ms)
```

### Offline Event Creation

Create events without internet connection:

```python
event = await create_calendar_event(
    summary="Team Sync",
    start="2026-01-15T10:00:00Z",
    end="2026-01-15T11:00:00Z",
    location="Conference Room A"
)
# Returns immediately with local:<uuid> ID
# Syncs to Google Calendar when worker runs
```

### Status Tracking

Events include a `_local_status` field indicating sync state:

- **`synced`**: Event is synchronized with Google Calendar (default, no badge shown)
- **`pending`**: Event awaiting background sync (shows `⏱ Pending` badge)
- **`conflict`**: Offline edit conflicted with server changes (shows `⚠ Conflict` badge)

### Calendar Selection

Users can choose which calendars to display via the web UI:

1. Navigate to **Settings** → **Calendar** section
2. Check/uncheck calendars to show/hide
3. Changes take effect immediately

Selected calendars are stored in user preferences and respected by both the web UI and MCP tools.

## Web UI

### Calendar Views

The calendar interface provides multiple views:

- **Day View**: Hourly breakdown with timed events
- **Week View**: 7-day grid with event blocks
- **Month View**: Monthly calendar with event pills
- **Agenda View**: List of upcoming events with details

All views show status badges for pending/conflict events.

### Event Management

- **Create**: Click time slot → Fill form → Saves to outbox → Syncs in background
- **Edit**: Click event → Modify details → Queues update → Syncs in background
- **Delete**: Click event → Delete → Soft-delete → Syncs in background

### Status Indicators

Events display visual indicators based on sync state:

- **No Badge**: Event is synced with Google Calendar
- **⏱ Pending**: Event/update awaiting sync to Google
- **⚠ Conflict**: Offline edit conflicted, needs resolution

## Background Sync Worker

### How It Works

The calendar worker runs continuously as a supervised process:

1. **Flush Outbox**: Process pending create/patch/delete operations
2. **Incremental Sync**: Fetch changes since last sync using sync tokens
3. **Update Cache**: Store new/updated events in local database
4. **Repeat**: Wait 60 seconds, run again

Every 24 hours, a full sync is performed to refresh the entire time window.

### Sync Tokens

The worker uses Google Calendar API's [sync tokens](https://developers.google.com/calendar/api/guides/sync) for efficient incremental sync:

- Only fetches events that changed since last sync
- Detects new events, updates, and deletions
- Handles sync token invalidation gracefully (automatic full sync)

### Monitoring

Check worker logs in Docker:

```bash
docker-compose logs -f workspace-secretary | grep calendar-worker
```

Look for:
- `=== Starting sync cycle ===`
- `Processing N pending outbox operations`
- `Incremental sync for calendar_id: N changes`
- `Full sync for calendar_id: fetched N events`
- `=== Sync cycle completed ===`

### Error Handling

The worker handles errors gracefully:

- **Sync token invalid**: Automatically performs full sync
- **Network failure**: Retries on next cycle (60s later)
- **Conflict detection**: Marks events as `conflict` for user review
- **Crash recovery**: Supervisor restarts worker automatically

## Database Schema

### calendar_events_cache

Stores cached events for instant queries:

| Column | Type | Description |
|--------|------|-------------|
| `calendar_id` | TEXT | Google Calendar ID |
| `event_id` | TEXT | Event ID (or `local:<uuid>` for pending) |
| `event_json` | JSON | Full event data from Google Calendar API |
| `start_ts_utc` | INTEGER | Start timestamp (epoch) for fast range queries |
| `start_date` | TEXT | Start date (YYYY-MM-DD) for day-based queries |
| `local_status` | TEXT | Sync status: `synced`, `pending`, `conflict` |
| `cached_at` | TIMESTAMP | When event was cached |

**Indexes:**
- `(calendar_id, start_ts_utc)` for time-based queries
- `(calendar_id, start_date)` for day-based queries

### calendar_outbox

Queues offline operations for background sync:

| Column | Type | Description |
|--------|------|-------------|
| `op_id` | SERIAL | Unique operation ID |
| `calendar_id` | TEXT | Target calendar |
| `event_id` | TEXT | Event ID (null for creates) |
| `op_type` | TEXT | Operation: `create`, `patch`, `delete` |
| `payload` | JSON | Event data for create/patch |
| `status` | TEXT | `pending`, `applied`, `failed` |
| `created_at` | TIMESTAMP | When operation was queued |
| `error` | TEXT | Error message if failed |

### calendar_sync_state

Tracks sync progress per calendar:

| Column | Type | Description |
|--------|------|-------------|
| `calendar_id` | TEXT | Google Calendar ID |
| `window_start` | TEXT | Start of cached time window (RFC3339) |
| `window_end` | TEXT | End of cached time window (RFC3339) |
| `sync_token` | TEXT | Google Calendar sync token for incremental sync |
| `status` | TEXT | `ok`, `error` |
| `last_full_sync_at` | TIMESTAMP | Last full sync timestamp |
| `last_incremental_sync_at` | TIMESTAMP | Last incremental sync timestamp |
| `last_error` | TEXT | Most recent error message |

## Performance

### Benchmarks

| Operation | Before (Direct API) | After (Cached) | Improvement |
|-----------|---------------------|----------------|-------------|
| List events (1 week) | ~500ms | ~50ms | **10x faster** |
| List events (1 month) | ~1200ms | ~80ms | **15x faster** |
| Calendar page load | ~1500ms | ~150ms | **10x faster** |
| Create event | ~300ms (blocking) | ~5ms (queued) | **60x faster** |

### Resource Usage

- **Database**: ~1KB per event (~365KB per year of events)
- **Memory**: ~50MB for worker process
- **CPU**: <1% during sync cycles
- **Network**: Sync traffic only (no per-query API calls)

## Conflict Resolution

When an offline edit conflicts with server changes, the system uses a **server-wins** strategy:

1. Worker detects conflict during sync
2. Event marked with `local_status="conflict"`
3. User sees `⚠ Conflict` badge in UI
4. Server version is preserved in cache
5. User can manually resolve by re-editing event

Future enhancement: Side-by-side conflict resolution UI.

## Troubleshooting

### Calendar Not Syncing

1. Check worker is running:
   ```bash
   docker-compose ps | grep calendar-worker
   ```

2. Check worker logs for errors:
   ```bash
   docker-compose logs calendar-worker
   ```

3. Verify OAuth2 token is valid:
   ```bash
   ls -la config/gmail-token.json
   ```

### Events Not Appearing

1. Check calendar is selected in settings:
   - Open Settings → Calendar
   - Ensure calendar checkbox is checked

2. Check sync state in database:
   ```sql
   SELECT * FROM calendar_sync_state WHERE calendar_id = 'your-calendar-id';
   ```

3. Force full sync by deleting sync token:
   ```sql
   UPDATE calendar_sync_state SET sync_token = NULL WHERE calendar_id = 'your-calendar-id';
   ```

### Pending Events Not Syncing

1. Check outbox for failed operations:
   ```sql
   SELECT * FROM calendar_outbox WHERE status = 'failed';
   ```

2. Review error messages in outbox:
   ```sql
   SELECT op_id, op_type, error FROM calendar_outbox WHERE status = 'failed';
   ```

3. Manually retry by resetting status:
   ```sql
   UPDATE calendar_outbox SET status = 'pending' WHERE op_id = 123;
   ```

## MCP Tools for LLMs

LLMs can interact with calendars via FastMCP tools (automatically benefit from caching):

### List Events

```python
events = await list_calendar_events(
    time_min="2026-01-12T00:00:00Z",
    time_max="2026-01-19T23:59:59Z",
    calendar_id="primary"  # Optional
)
```

Returns list of events with `_local_status` field indicating sync state.

### Create Event

```python
event = await create_calendar_event(
    summary="Team Meeting",
    start="2026-01-15T10:00:00-08:00",
    end="2026-01-15T11:00:00-08:00",
    location="Conference Room A",
    description="Quarterly planning discussion",
    attendees=["alice@example.com", "bob@example.com"]
)
```

Returns immediately with `local:<uuid>` ID. Syncs in background.

### Get Availability

```python
availability = await get_calendar_availability(
    time_min="2026-01-15T00:00:00Z",
    time_max="2026-01-15T23:59:59Z"
)
```

Uses cached events for instant freebusy calculation.

## Next Steps

- [Configuration Guide](./configuration) - Full config reference
- [Web UI Guide](./web-ui) - Web interface documentation
- [Docker Deployment](./docker) - Deployment guide
- [Security](./security) - Security best practices
