# Intelligence Tools

Smart analysis, prioritization, and batch processing tools.

::: tip AI-Native Design
These tools return **signals** for AI reasoning—they don't make decisions. The AI interprets signals in context to determine priority and actions.
:::

## get_daily_briefing

Combined calendar + email intelligence for a given day.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `date` | string | Yes | Target date (YYYY-MM-DD) |

**Returns:**
```json
{
  "date": "2026-01-09",
  "timezone": "America/Los_Angeles",
  "calendar_events": [
    {
      "summary": "Team Standup",
      "start": "09:30",
      "end": "10:00",
      "attendees": ["team@company.com"]
    }
  ],
  "email_candidates": [
    {
      "uid": 12345,
      "subject": "Quick question about budget",
      "from": "cfo@company.com",
      "date": "2026-01-09T08:15:00Z",
      "snippet": "Do you have a moment to discuss...",
      "signals": {
        "is_addressed_to_me": true,
        "mentions_my_name": false,
        "is_from_vip": true,
        "is_important": false,
        "has_question": true,
        "mentions_deadline": false,
        "mentions_meeting": false
      }
    }
  ]
}
```

### Signals Reference

| Signal | How Detected | Example Triggers |
|--------|--------------|------------------|
| `is_addressed_to_me` | User's email in To: field | Direct recipient |
| `mentions_my_name` | Full name in body | "Hi John," or "Ask John about..." |
| `is_from_vip` | Sender in `vip_senders` config | Configured priority senders |
| `is_important` | Gmail IMPORTANT label | Gmail's importance algorithm |
| `has_question` | `?` or request phrases | "Can you...", "Would you...", "?" |
| `mentions_deadline` | Urgency keywords | EOD, ASAP, urgent, deadline, due |
| `mentions_meeting` | Scheduling keywords | meet, schedule, calendar, zoom, call |

::: warning Signals ≠ Decisions
The AI should interpret signals in context:
- `is_from_vip + has_question` → Likely high priority
- `mentions_deadline` from newsletter → Ignore
- `is_addressed_to_me` with 50 recipients → May be low priority
:::

**Classification:** Read-only ✅

## quick_clean_inbox

Identify emails that can be safely auto-cleaned (moved to archive).

::: tip Time-Boxed with Continuation
This tool processes for ~5 seconds then returns partial results with a continuation state. Call again with the state to continue.
:::

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `continuation_state` | string | No | State from previous call |
| `time_limit_seconds` | number | No | Processing time (default: 5) |

**Safety Criteria (ALL must be true):**
1. User is NOT in To: field
2. User is NOT in CC: field  
3. User's email is NOT mentioned in body
4. User's name is NOT mentioned in body

**Returns:**
```json
{
  "status": "partial",
  "has_more": true,
  "continuation_state": "eyJvZmZzZXQiOjQ1Li4ufQ==",
  "processed_count": 45,
  "candidates": [
    {
      "uid": 12340,
      "from": "newsletter@company.com",
      "subject": "Weekly Digest #234",
      "date": "2026-01-07",
      "confidence": "high",
      "reason": "User not in To/CC, not mentioned"
    }
  ],
  "time_limit_reached": true
}
```

**Continuation Pattern:**
```python
# Aggregate all candidates across batches
all_candidates = []
state = None

while True:
    result = quick_clean_inbox(continuation_state=state)
    all_candidates.extend(result["candidates"])
    
    if result["status"] == "complete" or not result["has_more"]:
        break
    state = result["continuation_state"]

# Now present complete list to user for approval
```

**Classification:** Read-only ✅ (identifies only, doesn't move)

## execute_clean_batch

Execute approved cleanup by moving emails.

::: danger Mutation Tool
**Only call after user approves candidates from `quick_clean_inbox`.**
:::

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uids` | array | Yes | Email UIDs to move |
| `mark_read` | boolean | No | Mark as read (default: true) |

**Returns:**
```json
{
  "status": "success",
  "moved_count": 15,
  "target_folder": "Secretary/Auto-Cleaned",
  "failed": []
}
```

**Classification:** Mutation 🔴 (requires user approval of candidate list)

## triage_priority_emails

Identify high-priority emails for immediate attention.

::: tip Time-Boxed with Continuation
Uses same continuation pattern as `quick_clean_inbox`.
:::

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `continuation_state` | string | No | State from previous call |

**Priority Criteria (ANY triggers priority):**
1. User in To: field with **<5 total recipients**, OR
2. User in To: field with **<15 recipients** AND user's name mentioned in body

**Returns:**
```json
{
  "status": "complete",
  "has_more": false,
  "priority_emails": [
    {
      "uid": 12345,
      "from": "boss@company.com",
      "subject": "Quick question",
      "date": "2026-01-09T10:30:00Z",
      "to_count": 2,
      "snippet": "Hey, do you have a minute to...",
      "priority_reason": "direct_small_group (2 recipients)",
      "signals": {
        "is_from_vip": true,
        "has_question": true,
        "mentions_deadline": false
      }
    }
  ],
  "priority_count": 8,
  "processed_count": 150
}
```
**Classification:** Read-only ✅

## triage_remaining_emails

Process emails that don't match auto-clean or priority criteria.

Uses the same continuation pattern as other batch tools.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `continuation_state` | string | No | State from previous call |

**Targets emails where:**
- User IS in To: or CC: (not auto-cleanable)
- Does NOT meet priority criteria (larger groups, CC only)

**Returns:**
```json
{
  "status": "complete",
  "remaining_emails": [
    {
      "uid": 12350,
      "from": "team@company.com",
      "subject": "FYI: Server Maintenance",
      "date": "2026-01-09T08:00:00Z",
      "user_in_to": false,
      "user_in_cc": true,
      "to_count": 25,
      "signals": {
        "is_from_vip": false,
        "name_mentioned": false,
        "has_question": false,
        "mentions_deadline": false
      }
    }
  ],
  "remaining_count": 15
}
```

**Classification:** Read-only ✅

## summarize_thread

Get structured summary of email thread for AI context efficiency.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thread_id` | string | Yes | Thread ID |

**Returns:**
```json
{
  "thread_id": "thread_abc",
  "subject": "Re: Q1 Planning",
  "participants": ["you@gmail.com", "team@company.com", "manager@company.com"],
  "message_count": 8,
  "date_range": {
    "first": "2026-01-05T09:00:00Z",
    "last": "2026-01-09T14:30:00Z"
  },
  "key_points": [
    "Budget approved for Q1",
    "Timeline: Launch by March 15",
    "John to lead technical review"
  ],
  "action_items": [
    "Schedule kickoff meeting",
    "Share resource plan by Friday"
  ],
  "latest_message": {
    "from": "manager@company.com",
    "date": "2026-01-09T14:30:00Z",
    "snippet": "Looks good, let's proceed with..."
  }
}
```

**Classification:** Read-only ✅

## Workflow Patterns

### Morning Briefing Pattern

```
1. get_daily_briefing(date="today")
2. Review calendar_events for the day
3. Analyze email_candidates signals:
   - is_from_vip + has_question → Present first
   - mentions_deadline → Flag urgency
   - is_addressed_to_me + small group → Needs response
4. Present prioritized summary to user
```

### Inbox Triage Pattern

```
1. quick_clean_inbox() → Loop until complete
2. Present candidates to user, grouped by confidence
3. User approves → execute_clean_batch(uids=[...])
4. triage_priority_emails() → Loop until complete
5. Present priority emails with signals
6. triage_remaining_emails() → Loop until complete
7. Present remaining for user decision
```

### Context-Aware Reply Pattern

```
1. get_email_details(uid=12345) → Read the email
2. find_related_emails(uid=12345) → Get context (if semantic search enabled)
3. Review related emails for commitments, decisions, history
4. create_draft_reply() → Draft response with context
5. Present draft to user for approval
6. User approves → send_email()
```

---

## setup_smart_labels

Set up the Secretary folder hierarchy for organizing emails.

Creates Gmail labels for email triage workflow:
- `Secretary/Priority` - High-priority emails needing attention
- `Secretary/Action-Required` - Emails requiring response
- `Secretary/Processed` - Emails that have been handled
- `Secretary/Calendar` - Meeting invitations and calendar-related
- `Secretary/Newsletter` - Newsletters and automated mail
- `Secretary/Waiting` - Emails awaiting responses

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dry_run` | boolean | No | If true, only report what would be created (default: false) |

**Returns:**
```
Created: Secretary/Priority
Created: Secretary/Action-Required
Created: Secretary/Processed
Created: Secretary/Calendar
Created: Secretary/Newsletter
Created: Secretary/Waiting

All labels created successfully.
```

**Classification:** Staging ✅ (idempotent, safe to run)

---

**Next:** [Email Tools](./email) | [Calendar Tools](./calendar)
