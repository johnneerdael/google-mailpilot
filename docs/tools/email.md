# Email Tools

Email and search tools for reading, searching, and managing emails.

::: tip Cache-First Performance
Read operations query the local SQLite cache first, providing **sub-millisecond response times**. The cache syncs with Gmail IMAP every 5 minutes automatically.
:::

## gmail_search

Search emails using Gmail-style query syntax.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (Gmail syntax) |
| `max_results` | number | No | Max results (default: 50) |

**Query Syntax Examples:**
```
from:boss@company.com
subject:invoice
has:attachment
after:2026-01-01 before:2026-01-31
from:vip@company.com is:unread
```

**Returns:**
```json
{
  "results": [
    {
      "uid": 12345,
      "thread_id": "thread_abc",
      "subject": "Q1 Budget Review",
      "from": "boss@company.com",
      "date": "2026-01-08T14:30:00Z",
      "snippet": "Please review the attached budget..."
    }
  ]
}
```

**Classification:** Read-only ✅

## search_emails

Search emails using structured criteria with database queries.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `folder` | string | No | Folder to search in (default: "INBOX") |
| `from_addr` | string | No | Filter by sender address (partial match) |
| `to_addr` | string | No | Filter by recipient address (partial match) |
| `subject` | string | No | Filter by subject (partial match) |
| `body` | string | No | Filter by body content (partial match) |
| `unread_only` | boolean | No | Only return unread emails (default: false) |
| `limit` | number | No | Max results (default: 50) |

**Returns:** Array of email objects with `uid`, `subject`, `from`, `date`, `snippet`

**Classification:** Read-only ✅

**Example:**
```json
{
  "folder": "INBOX",
  "from_addr": "boss",
  "unread_only": true,
  "limit": 10
}
```

**Response:**
```json
[
  {
    "uid": 12345,
    "subject": "Q1 Budget Review",
    "from": "boss@company.com",
    "date": "2026-01-08T14:30:00Z",
    "snippet": "Please review the attached budget...",
    "is_unread": true,
    "flags": ["\\Seen"]
  }
]
```

## get_unread_messages

Fetch recent unread emails with basic metadata.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | number | No | Max emails (default: 20) |

**Returns:**
```json
{
  "messages": [
    {
      "uid": 12345,
      "subject": "Meeting Tomorrow",
      "from": "colleague@company.com",
      "date": "2026-01-09T09:00:00Z",
      "snippet": "Hi, can we meet at 3pm..."
    }
  ],
  "total_unread": 15
}
```

**Classification:** Read-only ✅

## get_email_details

Get full email content including attachments metadata.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Email UID |
| `folder` | string | No | Folder name (default: INBOX) |

**Returns:**
```json
{
  "uid": 12345,
  "subject": "Q1 Report",
  "from": "reports@company.com",
  "to": ["you@gmail.com"],
  "cc": ["team@company.com"],
  "date": "2026-01-09T10:00:00Z",
  "body": "Full email body text...",
  "attachments": [
    {
      "filename": "Q1-Report.pdf",
      "size": 245678,
      "content_type": "application/pdf",
      "attachment_id": "att_abc123"
    }
  ]
}
```

**Classification:** Read-only ✅

## gmail_get_thread / get_thread

Retrieve entire conversation thread.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thread_id` | string | Yes | Thread ID from search results |

**Returns:**
```json
{
  "thread_id": "thread_abc",
  "subject": "Re: Project Update",
  "messages": [
    {
      "uid": 12340,
      "from": "colleague@company.com",
      "to": ["you@gmail.com"],
      "date": "2026-01-07T14:00:00Z",
      "body": "Here's the initial update..."
    },
    {
      "uid": 12345,
      "from": "you@gmail.com",
      "to": ["colleague@company.com"],
      "date": "2026-01-08T09:30:00Z",
      "body": "Thanks, I'll review..."
    }
  ]
}
```

**Classification:** Read-only ✅

## summarize_thread

Get a token-efficient summary of an email thread for AI context.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thread_id` | string | Yes | Thread ID |

**Returns:**
```json
{
  "thread_id": "thread_abc",
  "participants": ["you@gmail.com", "colleague@company.com"],
  "message_count": 5,
  "date_range": "Jan 7-9, 2026",
  "key_points": [
    "Project timeline discussed",
    "Budget approval pending",
    "Next meeting scheduled for Friday"
  ],
  "latest_message": {
    "from": "colleague@company.com",
    "date": "2026-01-09T10:00:00Z",
    "snippet": "Sounds good, see you Friday..."
  }
}
```

**Classification:** Read-only ✅

## send_email

Send an email message.

::: danger Mutation Tool
**Always show draft to user before calling.** See [AGENTS.md](/guide/agents#human-in-the-loop) for the draft-review-send pattern.
:::

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Recipient email |
| `subject` | string | Yes | Email subject |
| `body` | string | Yes | Email body (plain text or HTML) |
| `cc` | string | No | CC recipients (comma-separated) |
| `bcc` | string | No | BCC recipients |
| `reply_to_message_id` | string | No | Message ID for threading |

**Classification:** Mutation 🔴 (requires user confirmation)

## create_draft_reply

Create a draft reply in Gmail Drafts folder.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Original email UID |
| `folder` | string | Yes | Folder containing original email |
| `reply_body` | string | Yes | Draft reply body content |
| `reply_all` | boolean | No | Reply to all recipients (default: false) |

**Returns:**
```json
{
  "status": "success",
  "message": "Draft created",
  "draft_uid": "draft_xyz",
  "draft_folder": "[Gmail]/Drafts"
}
```

**Classification:** Staging ✅ (safe - creates draft, doesn't send)

**Example:**
```json
{
  "uid": 12345,
  "folder": "INBOX",
  "reply_body": "Thanks for your email. I'll review and get back to you.",
  "reply_all": false
}
```

## mark_as_read / mark_as_unread

Change email read status.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Email UID |
| `folder` | string | No | Folder name (default: INBOX) |

**Classification:** Mutation 🔴 (confirm for bulk operations)

## move_email

Move email to different folder.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Email UID |
| `destination` | string | Yes | Target folder name |
| `source` | string | No | Source folder (default: INBOX) |

**Classification:** Mutation 🔴 (requires confirmation)

## modify_gmail_labels

Add or remove Gmail labels.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Email UID |
| `add_labels` | array | No | Labels to add |
| `remove_labels` | array | No | Labels to remove |

**Classification:** Mutation 🔴 (requires confirmation)

## list_folders

List all synced email folders and their status.

**Parameters:** None

**Returns:**
```json
[
  {
    "name": "INBOX",
    "message_count": 150,
    "unread_count": 5,
    "sync_status": "synced"
  }
]
```

**Classification:** Read-only ✅

---

## trigger_sync

Trigger an immediate email synchronization with the mail server.

**Parameters:** None

**Returns:**
```json
{
  "status": "success",
  "message": "Sync triggered"
}
```

**Classification:** Read-only ✅

---

## process_email

Perform a generic action on an email (move, mark read/unread, delete).

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Email UID |
| `folder` | string | Yes | Source folder |
| `action` | string | Yes | Action: "move", "read", "unread", "delete" |
| `target_folder` | string | No | Target folder for "move" action |

**Example:**
```json
{
  "uid": 12345,
  "folder": "INBOX",
  "action": "move",
  "target_folder": "Projects"
}
```

**Classification:** Mutation 🔴 (requires confirmation)

---

## Semantic Search Tools

Available when PostgreSQL + pgvector is configured:

### semantic_search_emails

Search emails by meaning, not keywords.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language search |
| `folder` | string | No | Folder to search (default: INBOX) |
| `limit` | number | No | Max results (default: 20) |
| `similarity_threshold` | float | No | Min similarity 0-1 (default: 0.7) |

**Example queries:**
- "emails about budget concerns"
- "discussions about project delays"
- "messages asking for my opinion"

**Classification:** Read-only ✅

### find_related_emails

Find emails similar to a reference email.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uid` | number | Yes | Reference email UID |
| `folder` | string | No | Folder (default: INBOX) |
| `limit` | number | No | Max results (default: 10) |

**Use case:** Gather context before drafting a reply.

**Classification:** Read-only ✅

### semantic_search_filtered

Combine hard filters with semantic similarity for precise search.

**Why use this?** Regular semantic search can find semantically similar emails from wrong senders or date ranges. This tool applies hard filters FIRST, then ranks results by semantic similarity.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language query |
| `folder` | string | No | Folder to search (default: INBOX) |
| `from_addr` | string | No | Filter by sender (partial match) |
| `to_addr` | string | No | Filter by recipient (partial match) |
| `date_from` | string | No | Filter emails on/after (YYYY-MM-DD) |
| `date_to` | string | No | Filter emails on/before (YYYY-MM-DD) |
| `has_attachments` | boolean | No | Filter by attachment presence |
| `limit` | number | No | Max results (default: 20) |

**Example:**
```json
{
  "query": "budget concerns",
  "from_addr": "finance",
  "date_from": "2026-01-01",
  "has_attachments": true
}
```

**Classification:** Read-only ✅

---

**Next:** [Calendar Tools](./calendar) | [Intelligence Tools](./intelligence)
