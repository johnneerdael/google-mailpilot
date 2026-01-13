# MCP Tools Reference

Complete reference for all Gmail Secretary MCP tools.

::: tip AI-Native Design
These aren't protocol wrappers—they're **secretary workflows** designed for AI assistants:
- **Signals** for intelligent reasoning, not raw data
- **Staged mutations** that require user confirmation
- **Time-boxed batches** with continuation states for large mailboxes
:::

## Tool Categories

| Category | Purpose |
|----------|---------|
| [Email & Search](./email) | Read, search, and analyze emails |
| [Calendar](./calendar) | Manage calendar events and availability |
| [Intelligence](./intelligence) | Daily briefings, triage, and smart cleanup |

## Safety Classifications

All tools are classified by their mutation behavior:

| Classification | Description | Confirmation Required |
|----------------|-------------|----------------------|
| **Read-Only** | Query data, no changes | No |
| **Staging** | Prepare changes (drafts) | No |
| **Mutation** | Execute changes | **Yes** |

### Read-Only Tools (Always Safe)
- `get_unread_messages` - Fetch unread emails
- `search_emails` / `gmail_search` - Search emails
- `get_email_details` - Get full email content
- `get_thread` / `gmail_get_thread` - Get conversation thread
- `summarize_thread` - Summarized thread for AI context
- `check_calendar` / `list_calendar_events` - Query calendar
- `get_daily_briefing` - Combined email + calendar intelligence
- `quick_clean_inbox` - **Identify** cleanup candidates (doesn't move)
- `triage_priority_emails` - **Identify** priority emails
- `triage_remaining_emails` - **Identify** remaining emails
- `semantic_search_emails` - Search by meaning (pgvector only)
- `find_related_emails` - Find similar emails (pgvector only)
- `get_embedding_status` - Check semantic search health

### Staging Tools (Safe)
- `create_draft_reply` - Create draft in Gmail Drafts folder
- `suggest_reschedule` - Suggest meeting times (no calendar changes)

### Mutation Tools (Require Confirmation)
- `send_email` 🔴 - Send email (always show draft first)
- `mark_as_read` / `mark_as_unread` 🔴 - Change read status
- `move_email` 🔴 - Move to folder
- `modify_gmail_labels` 🔴 - Add/remove labels
- `execute_clean_batch` 🔴 - Execute approved cleanup
- `create_calendar_event` 🔴 - Create calendar event
- `process_meeting_invite` 🔴 - Accept/decline invite

## Response Format

All tools return MCP-standard responses:

**Success:**
```json
{
  "content": [
    {
      "type": "text",
      "text": "Found 5 unread emails..."
    }
  ],
  "isError": false
}
```

**Error:**
```json
{
  "content": [
    {
      "type": "text", 
      "text": "Error: Invalid folder name"
    }
  ],
  "isError": true
}
```

## Signals System

Intelligence tools return **signals** for AI reasoning:

| Signal | Meaning |
|--------|---------|
| `is_addressed_to_me` | User's email in To: field |
| `mentions_my_name` | User's full name in body |
| `is_from_vip` | Sender in `vip_senders` config |
| `is_important` | Gmail IMPORTANT label |
| `has_question` | Contains `?` or request language |
| `mentions_deadline` | EOD, ASAP, urgent, etc. |
| `mentions_meeting` | meet, schedule, calendar, etc. |

**Signals inform decisions—they don't make them.** Context matters:
- "Urgent" from a vendor on Friday 5pm → probably low priority
- Calm question from CEO on Monday → probably high priority

## Time-Boxed Batch Tools

Large mailboxes use **continuation states** to avoid timeouts:

```python
# First call - processes ~5 seconds worth
result = quick_clean_inbox()
# {"status": "partial", "has_more": true, "continuation_state": "..."}

# Continue from where we left off
result = quick_clean_inbox(continuation_state=result["continuation_state"])
# {"status": "complete", "has_more": false, "candidates": [...]}
```

Tools with continuation support:
- `quick_clean_inbox`
- `triage_priority_emails`
- `triage_remaining_emails`

## Semantic Search Tools

When PostgreSQL + pgvector is configured:

| Tool | Purpose |
|------|---------|
| `semantic_search_emails` | Find emails by meaning ("budget concerns") |
| `find_related_emails` | Find emails similar to a reference email |
| `get_embedding_status` | Check embeddings health |

See [Semantic Search Guide](/guide/semantic-search) for setup.

## Quick Reference

### Email Operations

| Tool | Purpose | Classification |
|------|---------|---------------|
| `get_unread_messages` | Fetch recent unread | Read-only |
| `search_emails` | Structured search | Read-only |
| `gmail_search` | Gmail query syntax | Read-only |
| `list_folders` | List all synced folders | Read-only |
| `get_email_details` | Full email content | Read-only |
| `get_thread` | Conversation thread | Read-only |
| `summarize_thread` | Thread summary | Read-only |
| `send_email` | Send email | **Mutation** |
| `create_draft_reply` | Create draft | Staging |
| `mark_as_read` | Mark as read | **Mutation** |
| `mark_as_unread` | Mark as unread | **Mutation** |
| `move_email` | Move to folder | **Mutation** |
| `modify_gmail_labels` | Modify labels | **Mutation** |
| `process_email` | Generic email action | **Mutation** |
| `trigger_sync` | Force email sync | Read-only |

### Calendar Operations

| Tool | Purpose | Classification |
|------|---------|---------------|
| `get_calendar_availability` | Check availability | Read-only |
| `list_calendar_events` | List events | Read-only |
| `suggest_reschedule` | Find meeting times | Staging |
| `create_calendar_event` | Create event | **Mutation** |
| `respond_to_meeting` | Accept/decline invite | **Mutation** |

### Intelligence Operations

| Tool | Purpose | Classification |
|------|---------|---------------|
| `get_daily_briefing` | Calendar + email intelligence | Read-only |
| `summarize_thread` | Thread summary | Read-only |
| `quick_clean_inbox` | Identify cleanup candidates | Read-only |
| `execute_clean_batch` | Execute approved cleanup | **Mutation** |
| `triage_priority_emails` | Identify priority emails | Read-only |
| `triage_remaining_emails` | Process remaining emails | Read-only |

### Semantic Search (PostgreSQL + pgvector)

| Tool | Purpose | Classification |
|------|---------|---------------|
| `semantic_search_emails` | Search by meaning | Read-only |
| `semantic_search_filtered` | Metadata + semantic search | Read-only |
| `find_related_emails` | Find similar emails | Read-only |

### Utility Operations

| Tool | Purpose | Classification |
|------|---------|---------------|
| `setup_smart_labels` | Setup folder hierarchy | Staging |
| `create_task` | Create task in tasks.md | Staging |

## Rate Limits

Gmail has rate limits that the server respects:
- **IMAP connections**: ~15 concurrent connections per account
- **Email operations**: ~250 quota units/second

The server uses connection pooling and doesn't implement additional rate limiting.

## Next Steps

- [Email Tools Reference](./email) - Detailed email tool docs
- [Calendar Tools Reference](./calendar) - Detailed calendar tool docs
- [Intelligence Tools Reference](./intelligence) - Briefing and analysis tools
- [Agent Patterns](/guide/agents) - Building intelligent workflows
