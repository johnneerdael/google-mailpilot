# Mutation Journal

The Mutation Journal is a critical infrastructure component that enables **optimistic updates** in the Web UI while maintaining **eventual consistency** with Gmail's IMAP server. This guide explains the problem it solves, how it works, and how to monitor it.

## The Problem: DB/IMAP Consistency

Google MailPilot maintains a local database cache of your emails for fast search and display. When you perform an action in the Web UI (archive, delete, mark read), two things must happen:

1. **Update the local database** (instant UI feedback)
2. **Execute the IMAP command** (actually move the email on Gmail)

Without careful coordination, these can get out of sync:

```
Timeline of Disaster (without Mutation Journal):

T=0  User clicks "Archive" on email #123
T=1  Web UI updates DB: folder = "Archive"     ✓ User sees email disappear
T=2  IMAP command fails (network timeout)       ✗ Gmail still has it in INBOX
T=3  Sync engine runs
T=4  Sync sees email in INBOX, overwrites DB    ✗ Email reappears!
T=5  User: "I already archived that?!"
```

### Real-World Failure Scenarios

| Scenario | What Happens | User Experience |
|----------|--------------|-----------------|
| Network blip during archive | DB updated, IMAP fails | Email reappears on next sync |
| Gmail rate limit hit | IMAP returns error 429 | Labels not applied, no feedback |
| Server timeout on bulk delete | Partial execution | Some emails deleted, others remain |
| OAuth token expired mid-operation | Auth failure | Action silently fails |

The Mutation Journal solves all of these by:
1. Recording the intended operation **before** executing it
2. Storing the original state for rollback
3. Preventing sync from clobbering pending changes
4. Providing restore capability for completed operations

## How It Works

### The Optimistic Update Pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Web UI User Action                          │
│                    (User clicks "Archive")                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 1: RECORD PRE-STATE                                           │
│  ─────────────────────────────────────────────────────────────────  │
│  INSERT INTO mutation_journal (                                     │
│    email_uid = 123,                                                 │
│    email_folder = 'INBOX',                                          │
│    action = 'MOVE',                                                 │
│    params = '{"target_folder": "[Gmail]/All Mail"}',                │
│    pre_state = '{"folder": "INBOX", "gmail_labels": ["\\Inbox"]}',  │
│    status = 'PENDING'                                               │
│  )                                                                  │
│  Returns: mutation_id = 42                                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 2: OPTIMISTIC DB UPDATE                                       │
│  ─────────────────────────────────────────────────────────────────  │
│  UPDATE emails SET                                                  │
│    folder = '[Gmail]/All Mail',                                     │
│    gmail_labels = '["\\All"]'                                       │
│  WHERE uid = 123 AND folder = 'INBOX'                               │
│                                                                     │
│  → UI immediately reflects the change                               │
│  → User sees email disappear from Inbox                             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 3: EXECUTE IMAP OPERATION                                     │
│  ─────────────────────────────────────────────────────────────────  │
│  engine_client.move_email(                                          │
│    uid = 123,                                                       │
│    source_folder = 'INBOX',                                         │
│    target_folder = '[Gmail]/All Mail'                               │
│  )                                                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │     SUCCESS       │           │     FAILURE       │
        └─────────┬─────────┘           └─────────┬─────────┘
                  │                               │
                  ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ UPDATE mutation   │           │ ROLLBACK from     │
        │ SET status =      │           │ pre_state:        │
        │ 'COMPLETED'       │           │                   │
        │                   │           │ UPDATE emails SET │
        │ Mutation remains  │           │   folder = 'INBOX'│
        │ for restore       │           │ WHERE uid = 123   │
        │ capability        │           │                   │
        │                   │           │ UPDATE mutation   │
        │                   │           │ SET status =      │
        │                   │           │ 'FAILED',         │
        │                   │           │ error = '...'     │
        └───────────────────┘           └───────────────────┘
```

### Sync Engine Integration

The sync engine must respect pending mutations to avoid "clobbering" optimistic updates:

```python
def sync_email_from_imap(email_data: dict):
    """Called by sync engine when it receives email state from IMAP."""
    
    # Check for pending mutations FIRST
    pending = db.get_pending_mutations(
        email_uid=email_data["uid"],
        email_folder=email_data["folder"]
    )
    
    if pending:
        # SKIP this email - mutation in progress
        # The mutation handler will sync after completing
        logger.info(
            f"Skipping sync for UID {email_data['uid']}: "
            f"{len(pending)} pending mutation(s)"
        )
        return
    
    # Safe to sync from IMAP - no pending mutations
    db.upsert_email(email_data)
```

This prevents the race condition:

```
WITH Mutation Journal:

T=0  User clicks "Archive" on email #123
T=1  mutation_journal: status='PENDING', pre_state saved
T=2  DB updated: folder = "Archive"      ✓ User sees email disappear
T=3  IMAP command fails (network timeout)
T=4  DB rolled back from pre_state       ✓ Email correctly reappears
T=5  User notified: "Archive failed"     ✓ Clear feedback

T=6  Sync engine runs
T=7  Sync checks mutation_journal: no PENDING mutations
T=8  Sync proceeds normally               ✓ No clobbering
```

## Schema Reference

### mutation_journal Table

```sql
CREATE TABLE mutation_journal (
    id SERIAL PRIMARY KEY,
    
    -- Target email identification
    email_uid INTEGER NOT NULL,
    email_folder TEXT NOT NULL,
    
    -- What operation was requested
    action TEXT NOT NULL,           -- 'MOVE', 'LABEL', 'FLAG', 'DELETE', 'SEND'
    params JSONB,                   -- Action-specific parameters
    
    -- State tracking
    status TEXT DEFAULT 'PENDING',  -- 'PENDING', 'COMPLETED', 'FAILED'
    pre_state JSONB,                -- Original state for rollback/restore
    error TEXT,                     -- Error message if FAILED
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Foreign key (soft - email may be deleted)
    CONSTRAINT fk_email FOREIGN KEY (email_uid, email_folder) 
        REFERENCES emails(uid, folder) ON DELETE SET NULL
);

-- Index for sync engine lookups
CREATE INDEX idx_mutation_pending 
    ON mutation_journal(email_uid, email_folder) 
    WHERE status = 'PENDING';

-- Index for cleanup queries
CREATE INDEX idx_mutation_status_time 
    ON mutation_journal(status, created_at);
```

### Status Lifecycle

```
                    ┌──────────────┐
                    │   PENDING    │
                    │              │
                    │ Waiting for  │
                    │ IMAP result  │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
     ┌────────────────┐       ┌────────────────┐
     │   COMPLETED    │       │    FAILED      │
     │                │       │                │
     │ IMAP succeeded │       │ IMAP error     │
     │ DB consistent  │       │ DB rolled back │
     │                │       │                │
     │ Restorable*    │       │ Needs review   │
     └────────────────┘       └────────────────┘
     
     * If action is reversible (not SEND or permanent DELETE)
```

## Action Types

### MOVE Action

Moving an email between folders (Archive, Trash, custom folders).

```json
{
  "action": "MOVE",
  "params": {
    "target_folder": "[Gmail]/All Mail"
  },
  "pre_state": {
    "folder": "INBOX",
    "gmail_labels": ["\\Inbox", "UNREAD"]
  }
}
```

**IMAP Command**: `COPY` to target + `STORE \Deleted` + `EXPUNGE`

**Reversible**: Yes - move back to original folder

### LABEL Action

Adding or removing Gmail labels.

```json
{
  "action": "LABEL",
  "params": {
    "add": ["Important", "Project-X"],
    "remove": ["UNREAD"]
  },
  "pre_state": {
    "gmail_labels": ["\\Inbox", "UNREAD"]
  }
}
```

**IMAP Command**: `STORE +X-GM-LABELS` / `STORE -X-GM-LABELS`

**Reversible**: Yes - apply inverse label changes

### FLAG Action

Marking emails read/unread or starred/unstarred.

```json
{
  "action": "FLAG",
  "params": {
    "is_unread": false,
    "is_starred": true
  },
  "pre_state": {
    "is_unread": true,
    "is_starred": false,
    "flags": "\\Seen"
  }
}
```

**IMAP Command**: `STORE +FLAGS (\Seen)` / `STORE -FLAGS (\Seen)`

**Reversible**: Yes - toggle flags back

### DELETE Action

Moving to Trash or permanent deletion.

```json
{
  "action": "DELETE",
  "params": {
    "permanent": false
  },
  "pre_state": {
    "folder": "INBOX",
    "gmail_labels": ["\\Inbox"]
  }
}
```

**IMAP Command**: 
- `permanent: false` → Move to `[Gmail]/Trash`
- `permanent: true` → `STORE \Deleted` + `EXPUNGE` (in Trash)

**Reversible**: 
- `permanent: false` → Yes (move out of Trash)
- `permanent: true` → **NO** (data loss)

### SEND Action

Sending an email via SMTP.

```json
{
  "action": "SEND",
  "params": {
    "to": "sarah@example.com",
    "subject": "Re: Meeting Tomorrow",
    "message_id": "<generated-id@gmail.com>"
  },
  "pre_state": null
}
```

**SMTP Command**: Send via authenticated SMTP

**Reversible**: **NO** - once delivered, cannot be unsent

::: danger Irreversible Actions
SEND and permanent DELETE cannot be undone. The Mutation Journal records them for audit purposes, but `restore` operations will fail with an error explaining why.
:::

## Restore vs Undo

A critical distinction that affects user expectations:

| Concept | Restore | Undo |
|---------|---------|------|
| **What it does** | Applies inverse IMAP operation | Reverts database to previous state |
| **Scope** | Single mutation | Transaction rollback |
| **Works for** | MOVE, LABEL, FLAG, soft DELETE | N/A in this system |
| **Doesn't work for** | SEND, permanent DELETE | - |
| **Time limit** | None (while data exists) | N/A |
| **Creates new mutation** | Yes | No |

### Restore Flow

When a user clicks "Undo" in the UI (within a grace period or from history):

```python
async def restore_mutation(mutation_id: int) -> RestoreResult:
    """
    Attempt to restore (reverse) a completed mutation.
    Creates a NEW mutation that applies the inverse operation.
    """
    mutation = await db.get_mutation(mutation_id)
    
    if mutation is None:
        return RestoreResult(success=False, error="Mutation not found")
    
    if mutation["status"] != "COMPLETED":
        return RestoreResult(
            success=False, 
            error=f"Cannot restore mutation in {mutation['status']} status"
        )
    
    # Check if action is reversible
    if mutation["action"] == "SEND":
        return RestoreResult(
            success=False,
            error="Send actions cannot be reversed. Email already delivered.",
            reversible=False
        )
    
    if mutation["action"] == "DELETE" and mutation["params"].get("permanent"):
        return RestoreResult(
            success=False,
            error="Permanent deletions cannot be reversed. Data no longer exists.",
            reversible=False
        )
    
    # Build inverse operation
    if mutation["action"] == "MOVE":
        # Move back to original folder
        original_folder = mutation["pre_state"]["folder"]
        
        # Create new mutation for the restore
        restore_mutation_id = await db.create_mutation(
            email_uid=mutation["email_uid"],
            email_folder=mutation["params"]["target_folder"],  # Current location
            action="MOVE",
            params={"target_folder": original_folder},
            pre_state={"folder": mutation["params"]["target_folder"]}
        )
        
        # Execute the restore
        await engine_client.move_email(
            uid=mutation["email_uid"],
            source_folder=mutation["params"]["target_folder"],
            target_folder=original_folder
        )
        
        await db.update_mutation_status(restore_mutation_id, "COMPLETED")
        
        return RestoreResult(
            success=True,
            message=f"Email moved back to {original_folder}",
            restore_mutation_id=restore_mutation_id
        )
    
    elif mutation["action"] == "FLAG":
        # Restore original flags
        original_flags = mutation["pre_state"]
        
        restore_mutation_id = await db.create_mutation(
            email_uid=mutation["email_uid"],
            email_folder=mutation["email_folder"],
            action="FLAG",
            params=original_flags,
            pre_state=mutation["params"]  # Current state becomes pre_state
        )
        
        await engine_client.set_flags(
            uid=mutation["email_uid"],
            folder=mutation["email_folder"],
            **original_flags
        )
        
        await db.update_mutation_status(restore_mutation_id, "COMPLETED")
        
        return RestoreResult(
            success=True,
            message="Flags restored to original state",
            restore_mutation_id=restore_mutation_id
        )
    
    # ... similar for LABEL, soft DELETE
```

### Restore Chain Example

```
Original:  Email in INBOX, unread
    │
    ▼
Mutation #1: Archive (MOVE to All Mail)
    │         status=COMPLETED
    │         pre_state={folder: "INBOX"}
    ▼
Current:   Email in All Mail
    │
    ▼
Mutation #2: Restore #1 (MOVE to INBOX)  ← User clicks "Undo"
    │         status=COMPLETED
    │         pre_state={folder: "All Mail"}
    ▼
Current:   Email back in INBOX
    │
    ▼
Mutation #3: Restore #2 (MOVE to All Mail)  ← User clicks "Redo"
             status=COMPLETED
             pre_state={folder: "INBOX"}
```

Each restore creates a new mutation, maintaining full audit history.

## Edge Cases and Failure Modes

### UID Reassignment

Gmail may reassign UIDs when emails are moved between folders. This can break restore operations:

```
Problem:
1. Email #123 in INBOX
2. User archives → Email moved to All Mail
3. Gmail assigns NEW UID #456 in All Mail
4. Original mutation has email_uid=123, folder="INBOX"
5. Restore tries to find UID 123 in All Mail → NOT FOUND
```

**Mitigation**: Use `gmail_msgid` (X-GM-MSGID) as stable identifier when available:

```python
async def find_email_for_restore(mutation: dict) -> Optional[int]:
    """Find current UID for an email, even after UID changes."""
    
    # First try direct lookup
    email = await db.get_email_by_uid(
        mutation["email_uid"], 
        mutation["params"]["target_folder"]
    )
    if email:
        return email["uid"]
    
    # Fallback: search by gmail_msgid
    if mutation.get("pre_state", {}).get("gmail_msgid"):
        email = await db.search_emails(
            gmail_msgid=mutation["pre_state"]["gmail_msgid"]
        )
        if email:
            return email[0]["uid"]
    
    # Last resort: search by message_id header
    if mutation.get("pre_state", {}).get("message_id"):
        email = await db.search_emails(
            message_id=mutation["pre_state"]["message_id"]
        )
        if email:
            return email[0]["uid"]
    
    return None  # Email truly gone
```

### Bulk Operations

Bulk actions (archive 50 emails) can partially fail:

```python
async def bulk_archive(uids: list[int]) -> BulkResult:
    """Archive multiple emails with atomic mutation tracking."""
    
    results = []
    
    for uid in uids:
        mutation_id = await db.create_mutation(
            email_uid=uid,
            email_folder="INBOX",
            action="MOVE",
            params={"target_folder": "[Gmail]/All Mail"},
            pre_state=await get_email_state(uid)
        )
        
        try:
            await engine_client.move_email(uid, "INBOX", "[Gmail]/All Mail")
            await db.update_mutation_status(mutation_id, "COMPLETED")
            results.append({"uid": uid, "status": "success"})
            
        except Exception as e:
            # Rollback this specific email
            await rollback_from_pre_state(mutation_id)
            await db.update_mutation_status(
                mutation_id, "FAILED", error=str(e)
            )
            results.append({"uid": uid, "status": "failed", "error": str(e)})
    
    return BulkResult(
        total=len(uids),
        succeeded=len([r for r in results if r["status"] == "success"]),
        failed=len([r for r in results if r["status"] == "failed"]),
        details=results
    )
```

### Stuck Mutations

Mutations stuck in PENDING indicate engine issues:

```sql
-- Find mutations stuck for more than 5 minutes
SELECT * FROM mutation_journal 
WHERE status = 'PENDING' 
AND created_at < NOW() - INTERVAL '5 minutes';
```

**Recovery options**:

1. **Retry**: Re-execute the IMAP command
2. **Rollback**: Apply pre_state and mark FAILED
3. **Force complete**: Mark COMPLETED if IMAP actually succeeded

## Monitoring

### Admin Dashboard Widget

The Admin Dashboard (`/admin`) includes a Mutation Journal widget showing:

- Pending mutations count (should be 0 or very low)
- Failed mutations requiring review
- Recent mutation history
- Restore action buttons

### Health Checks

```python
async def check_mutation_health() -> HealthStatus:
    """Check mutation journal health for alerting."""
    
    with db.connection() as conn:
        # Count stuck mutations
        stuck = conn.execute("""
            SELECT COUNT(*) FROM mutation_journal 
            WHERE status = 'PENDING' 
            AND created_at < NOW() - INTERVAL '5 minutes'
        """).fetchone()[0]
        
        # Count recent failures
        failures = conn.execute("""
            SELECT COUNT(*) FROM mutation_journal 
            WHERE status = 'FAILED' 
            AND created_at > NOW() - INTERVAL '1 hour'
        """).fetchone()[0]
        
        if stuck > 0:
            return HealthStatus(
                status="critical",
                message=f"{stuck} mutations stuck in PENDING"
            )
        
        if failures > 5:
            return HealthStatus(
                status="warning", 
                message=f"{failures} mutations failed in last hour"
            )
        
        return HealthStatus(status="healthy")
```

### Alerting Integration

Configure email alerts in `config.yaml`:

```yaml
alerting:
  enabled: true
  recipient: admin@example.com
  
  thresholds:
    stuck_mutations: 1        # Alert if any mutations stuck > 5 min
    failed_mutations_hour: 5  # Alert if > 5 failures in 1 hour
```

## Cleanup and Retention

### Automatic Cleanup

```python
async def cleanup_old_mutations():
    """
    Remove old completed mutations to prevent unbounded growth.
    Run daily via scheduler.
    """
    with db.connection() as conn:
        deleted = conn.execute("""
            DELETE FROM mutation_journal 
            WHERE status = 'COMPLETED' 
            AND created_at < NOW() - INTERVAL '30 days'
            RETURNING id
        """).fetchall()
        
        logger.info(f"Cleaned up {len(deleted)} old mutations")
```

### Retention Policy

| Status | Retention | Reason |
|--------|-----------|--------|
| COMPLETED | 30 days | Restore capability window |
| FAILED | Indefinite | Requires manual review |
| PENDING | N/A | Should not exist long |

## API Reference

### POST /api/mutations/{id}/restore

Attempt to restore (reverse) a completed mutation.

**Request**: No body required

**Response (success)**:
```json
{
  "status": "success",
  "message": "Email moved back to INBOX",
  "restore_mutation_id": 43,
  "reversible": true
}
```

**Response (irreversible)**:
```json
{
  "status": "error",
  "message": "Send actions cannot be reversed",
  "reversible": false
}
```

**Response (not found)**:
```json
{
  "status": "error",
  "message": "Mutation not found",
  "reversible": null
}
```

### GET /api/mutations

List recent mutations with filtering.

**Query Parameters**:
- `status`: Filter by status (PENDING, COMPLETED, FAILED)
- `email_uid`: Filter by email UID
- `action`: Filter by action type
- `limit`: Max results (default 50)
- `offset`: Pagination offset

**Response**:
```json
{
  "mutations": [
    {
      "id": 42,
      "email_uid": 123,
      "email_folder": "INBOX",
      "action": "MOVE",
      "params": {"target_folder": "[Gmail]/All Mail"},
      "status": "COMPLETED",
      "pre_state": {"folder": "INBOX"},
      "created_at": "2026-01-11T10:30:00Z",
      "updated_at": "2026-01-11T10:30:01Z",
      "error": null
    }
  ],
  "total": 156,
  "has_more": true
}
```

### GET /api/mutations/health

Get mutation journal health status.

**Response**:
```json
{
  "status": "healthy",
  "pending_count": 0,
  "failed_count_1h": 2,
  "stuck_count": 0,
  "oldest_pending": null,
  "last_completed": "2026-01-11T10:45:00Z"
}
```

## Best Practices

### For Web UI Developers

1. **Always create mutation before optimistic update**
   ```python
   # CORRECT order
   mutation_id = await db.create_mutation(...)
   await db.update_email(...)  # Optimistic
   result = await engine.execute(...)
   await finalize_mutation(mutation_id, result)
   ```

2. **Show loading state during IMAP execution**
   - User sees immediate change (optimistic)
   - Subtle spinner indicates "syncing"
   - Toast notification on completion or failure

3. **Provide clear undo affordance**
   - "Archived. [Undo]" toast for 5 seconds
   - Undo triggers restore flow

### For Sync Engine Developers

1. **Always check pending mutations before overwriting**
   ```python
   if db.get_pending_mutations(uid, folder):
       return  # Skip - mutation in progress
   ```

2. **Log skipped syncs for debugging**
   ```python
   logger.debug(f"Skipped sync for {uid}: pending mutation")
   ```

### For Operations

1. **Monitor stuck mutations** - Any PENDING > 5 min is a problem
2. **Review failed mutations** - May indicate systemic issues
3. **Alert on thresholds** - Configure alerting in config.yaml
4. **Periodic cleanup** - Run cleanup job daily

## Limitations

1. **No true undo for sends**: Once SMTP delivers, the email is gone
2. **Permanent deletes are permanent**: No recovery from "Empty Trash" operations
3. **UID changes**: Complex folder operations may break restore if UIDs change
4. **Cross-account**: Mutations only work within single Gmail account
5. **Bulk partial failures**: Large batches may have mixed success/failure

## Future Enhancements

- [ ] Toast notification with "Undo" button (5-second window)
- [ ] Mutation history view in Settings
- [ ] Automatic retry for transient engine failures
- [ ] Batch mutation grouping for bulk actions
- [ ] Conflict resolution for concurrent mutations
- [ ] Export mutation history for compliance

## Related Documentation

- [Architecture Overview](/guide/architecture) - System design and data flow
- [Web UI Guide](./web-ui) - Using the web interface
- [Agent Patterns](./agents) - HITL safety patterns for AI agents
- [Security Guide](./security) - Authentication and data protection
