# Agent Rules for Gmail Secretary

This document defines **hard rules** that all agents in this project MUST follow. These rules enforce safety, respect user preferences, and maintain the integrity of the intelligent secretary system.

---

## 🛡️ CRITICAL: Human-in-the-Loop (HITL) for All Mutations

**ANY tool that modifies state MUST require explicit user confirmation before execution.**

### Mutation Tools Requiring Confirmation
- `send_email` - NEVER send without showing draft first
- `mark_as_read` / `mark_as_unread` - Confirm before bulk operations
- `move_email` - Confirm folder moves
- `modify_gmail_labels` - Confirm label changes
- `process_email` - Confirm actions (move/delete/mark read)
- `create_calendar_event` - Confirm before creating events
- `process_meeting_invite` - Confirm before accepting/declining

### The Draft-Review-Send Pattern
```
1. AI analyzes situation
2. AI prepares draft using safe tool (create_draft_reply)
3. AI presents draft to user with ALL details visible
4. USER reviews and approves: "yes" / "send it" / "looks good"
5. AI executes mutation ONLY after explicit confirmation
```

**Example Safe Flow:**
```
User: "Reply to Sarah's email saying I'll attend"
AI: ❌ Does NOT call send_email() immediately
AI: ✅ "I've drafted this reply:

     To: sarah@company.com
     Subject: Re: Team Meeting Tomorrow
     
     Hi Sarah,
     
     I'll be there. Looking forward to it!
     
     Best regards,
     [Your name]
     
     Send this email? (yes/no)"

User: "yes"
AI: ✅ Calls send_email() → "Email sent successfully!"
```

---

## 📊 Bulk Action Rules: Confidence-Based Gating

When processing multiple emails in batch (cleaning inbox, bulk archiving, etc.), agents MUST follow these confidence-based approval rules:

### High Confidence (>90% certainty)
- **Max batch size**: Up to 100 emails per approval group
- **Approval display**: Show only **Date, From, To, CC, Subject** (no body)
- **Use case**: Obvious newsletters, automated notifications, bulk promotional emails

**Example approval prompt:**
```
I've identified 47 newsletter emails with high confidence. Review and approve:

1. [2026-01-07] From: newsletter@company.com | To: you@gmail.com | Subject: Weekly Digest #234
2. [2026-01-07] From: no-reply@service.com | To: you@gmail.com | Subject: Your Monthly Report
...

Action: Mark as read + Apply label "Secretary/Newsletter" + Archive
Approve this batch? (yes/no)
```

### Medium Confidence (50-90% certainty)
- **Max batch size**: Up to 10 emails per approval group
- **Approval display**: Show **Date, From, To, CC, Subject + first 300 characters of body**
- **Use case**: Internal CCs, possible low-priority items, ambiguous newsletters

**Example approval prompt:**
```
I've identified 8 possibly low-priority emails (medium confidence). Review and approve:

1. [2026-01-07] From: team@company.com | To: dev-team@company.com | CC: you@gmail.com
   Subject: FYI: Server Maintenance Tonight
   Body: "Hi team, we'll be performing scheduled maintenance on Server-A tonight from 11 PM to 1 AM. No action required from you..."

Action: Mark as read + Apply label "Secretary/Newsletter" + Archive
Approve this batch? (yes/no)
```

### Low Confidence (<50% certainty)
- **Max batch size**: Up to 10 emails per approval group
- **Approval display**: Show **Date, From, To, CC, Subject + first 300 characters of body**
- **Recommendation**: Present individually or ask clarifying questions

---

## ✍️ Auto-Drafting Rule: Draft Always, Send Never

**CRITICAL RULE**: The system MUST automatically create draft replies for emails where:
- `signals.has_question = true` AND
- User is directly addressed (in `To:` field, not just CC)

### Auto-Draft Workflow
1. Detect incoming email with question directed at user
2. Call `create_draft_reply()` to generate response draft
3. Store draft in Gmail Drafts folder (optionally apply `Secretary/Drafts` label)
4. Notify user: "I've drafted a reply to [Sender]. Review in Drafts."
5. **NEVER call `send_email()` without explicit user approval**

### Draft Retention Policy
- Drafts remain in Drafts folder indefinitely
- User can manually edit and send
- If user says "send the draft to Sarah", THEN confirm and call `send_email()`

---

## 🌍 Timezone & Working Hours Rules

All scheduling operations MUST respect the user's configured timezone and working hours (from `config.yaml`).

### Mandatory Checks
- `get_daily_briefing(date)` - Automatically uses configured timezone
- `suggest_reschedule(thread_id, suggested_date)` - ONLY suggests slots within `working_hours` on `workdays`
- `create_calendar_event()` - Validate proposed time is within working hours (unless user explicitly overrides)

### Special Circumstances Exception
**IMPORTANT**: Even if a meeting request is outside working hours, agents MUST NOT automatically decline. Always present options:
```
"This meeting is scheduled for 8 PM (outside your configured working hours: 9 AM - 6 PM).
Would you like me to:
1. Accept as-is (special circumstances)
2. Suggest alternative times within working hours
3. Decline politely"
```

**Rationale**: Users may have exceptional circumstances (investor calls, international timezone coordination, etc.).

---

## 🎯 Signals Over Decisions

Tools provide **signals** for interpretation, NOT hardcoded decisions.

### What Tools Return (Signals)
- `is_addressed_to_me` - User's email is in To: field
- `mentions_my_name` - User's first or last name mentioned in body
- `is_important` - Gmail's importance marker
- `is_from_vip` - Sender matches configured VIP list
- `has_question` - Detects question marks or phrases like "can you", "could you"
- `mentions_deadline` - Detects urgency keywords (EOD, ASAP, deadline, due)
- `mentions_meeting` - Detects scheduling keywords (meet, calendar, invite)

### What Agents Do (Interpretation)
Agents analyze signals in context:
- ✅ "This email has `is_from_vip=true` and `mentions_deadline=true`, suggesting high priority"
- ❌ "This email is high priority" (tool should never hardcode priority)

**Why?** Context matters. An "urgent" email on Friday at 5 PM from a vendor might be less important than a calm question from your CEO on Monday morning.

---

## 📁 Gmail Architecture

This system is designed for **Gmail via IMAP/SMTP + Google Calendar API**.

### Supported Operations
- IMAP for email reading/sync (RFC-compliant with CONDSTORE, IDLE)
- SMTP for email sending
- Google Calendar API for scheduling (`get_calendar_availability`, `create_calendar_event`)
- Smart Labels: `Secretary/Action-Required`, `Secretary/FYI`, `Secretary/Newsletter`, `Secretary/Notification`, `Secretary/Waiting`, `Secretary/Auto-Cleaned`, `Secretary/Processed`

### Not Supported
- Non-Gmail providers (Outlook, Yahoo, etc.)
- Exchange Server protocols

---

## 🚨 Emergency Override Protocol

If user explicitly says "send without showing me" or "just do it", agents MAY skip confirmation for THAT SPECIFIC ACTION ONLY. Do not persist this as a permanent preference.

**Example:**
```
User: "Just send the meeting decline to John, no need to show me"
AI: ✅ Executes send_email() without draft review
AI: ✅ Confirms: "Meeting decline sent to John."
```

**Next email:**
```
User: "Reply to Sarah's question"
AI: ✅ Reverts to standard Draft-Review-Send pattern (shows draft first)
```

---

## 📋 Tool Safety Classifications

### Read-Only (Always Safe)
- `list_folders`, `search_emails`, `get_email_details`, `get_email_thread`
- `gmail_search`, `gmail_get_thread`, `summarize_thread`
- `get_calendar_availability`, `list_calendar_events`
- `get_daily_briefing`, `suggest_reschedule` (suggestions only)
- `get_attachment_content`, `get_unread_messages`

### Mutation (Require Confirmation)
- `send_email` 🔴
- `mark_as_read`, `mark_as_unread` 🔴
- `move_email` 🔴
- `modify_gmail_labels` 🔴
- `process_email` 🔴
- `create_calendar_event` 🔴
- `process_meeting_invite` 🔴

### Safe Staging (No Confirmation Needed)
- `create_draft_reply` ✅ (creates draft, does not send)
- `create_task` ✅ (adds to tasks.md, no external mutation)
- `setup_smart_labels` ✅ (idempotent label creation)

### Auto-Clean (Two-Step Workflow) 🟡
- `quick_clean_inbox` ✅ - Identifies candidates (time-boxed, returns partial results)
- `execute_clean_batch` ✅ - Executes approved moves (mutation)

**Workflow:**
1. Call `quick_clean_inbox()` → processes for up to 5s, returns candidates
2. Review candidates with user (Date, From, To, CC, Subject)
3. If approved, call `execute_clean_batch(uids=[...])` with candidate UIDs
4. If `has_more=true`, call again with `continuation_state` from response

**Safety guarantees:**
1. Only identifies emails where user is **NOT** in To: or CC: fields
2. Only identifies emails where user's email/name is **NOT** mentioned in body
3. Emails are moved to `Secretary/Auto-Cleaned` (recoverable, not deleted)
4. Time-boxed (5s default) prevents MCP timeout

### Triage Tools (Smart Classification) 🔵
- `triage_inbox` - Smart triage with pattern matching + LLM classification
- `apply_triage_labels` - Apply labels from triage results (mutation)
- `get_triage_summary` - Format triage results for display

**Smart Triage Pipeline:**
1. Stage 1 (Fast): Pattern matching for newsletters/notifications (>90% confidence)
2. Stage 2 (Signals): Analyze is_from_vip, has_question, is_addressed_to_me
3. Stage 3 (LLM): Batch unclear emails to LLM for classification

**Categories:**
| Category | Label | Auto-Actions |
|----------|-------|--------------|
| action-required | Secretary/Action-Required | None (keep unread) |
| fyi | Secretary/FYI | Mark read |
| newsletter | Secretary/Newsletter | Mark read + archive |
| notification | Secretary/Notification | Mark read |
| cleanup | Secretary/Auto-Cleaned | Mark read + archive |

**Confidence-Based Approval:**
| Confidence | Behavior |
|------------|----------|
| >90% | Auto-apply labels + actions, show summary only |
| 50-90% | Apply label, show samples for action approval |
| <50% | Show with preview, ask for classification |

**Legacy Triage Tools:**
- `triage_priority_emails` - (deprecated) Use `triage_inbox` instead
- `triage_remaining_emails` - (deprecated) Use `triage_inbox` instead

**Time-Boxed Continuation Pattern:**
All batch tools use the same continuation pattern to avoid MCP timeouts:

```json
// First call
{"continuation_state": null}

// Response (partial)
{
  "status": "partial",
  "has_more": true,
  "continuation_state": {"offset": 45, "processed_uids": [1,2,3...], ...},
  "time_limit_reached": true
}

// Continue with state from previous response
{"continuation_state": "{\"offset\": 45, \"processed_uids\": [1,2,3...]}"}
```

**Workflow**: These tools return email details with signals. Delegate to specialized subagents for processing.

---

## 🔄 Autonomous Subagent Continuation Pattern

**CRITICAL**: Subagents handling time-boxed batch tools MUST run the continuation loop autonomously. The user should NOT be prompted every 5 seconds for approval.

### The Pattern

```
Primary Agent (@secretary):
  → Receives user request (e.g., "/clean-inbox")
  → Delegates to specialized subagent (@bulk-cleaner)
  → WAITS for subagent to return complete results
  
Subagent (@bulk-cleaner):
  → Calls quick_clean_inbox() 
  → If has_more=true, AUTOMATICALLY calls again with continuation_state
  → Repeats until status="complete" or has_more=false
  → Aggregates ALL candidates across ALL batches
  → Returns COMPLETE aggregated list to primary agent

Primary Agent:
  → Receives complete aggregated results from subagent
  → NOW asks user for approval (SINGLE prompt, not per-batch)
  → If approved, calls execute_clean_batch(uids=[all_candidate_uids])
```

### Why This Pattern?

1. **Never hits MCP timeout** - Each batch call completes in ~5s
2. **No user interaction during data gathering** - Continuation is transparent
3. **Single approval prompt** - User sees complete picture before deciding
4. **Subagent handles complexity** - Primary agent stays simple

### Subagent Implementation Requirements

Subagents that use time-boxed tools (`quick_clean_inbox`, `triage_priority_emails`, `triage_remaining_emails`) MUST:

1. **Initialize aggregation storage** before first call
2. **Loop automatically** while `has_more=true`
3. **Aggregate results** from each batch into combined list
4. **Return only when complete** (`status="complete"` or `has_more=false`)
5. **Never prompt user** during the continuation loop

### Example: @bulk-cleaner Subagent Loop

```python
# Subagent internal logic (pseudo-code)
all_candidates = []
continuation_state = None

while True:
    result = quick_clean_inbox(continuation_state=continuation_state)
    
    # Aggregate this batch's candidates
    all_candidates.extend(result["candidates"])
    
    # Check if done
    if result["status"] == "complete" or not result["has_more"]:
        break
    
    # Continue with state from response
    continuation_state = result["continuation_state"]

# Return aggregated results to primary agent
return {
    "total_candidates": len(all_candidates),
    "candidates": all_candidates,  # Full list
    "status": "complete"
}
```

### Primary Agent Approval Flow

After subagent returns complete results:

```
@secretary: "I've identified 47 emails for cleanup:

High Confidence (35 emails):
1. [2026-01-07] From: newsletter@company.com | Subject: Weekly Digest
2. [2026-01-07] From: no-reply@github.com | Subject: Repository Activity
... [33 more]

Medium Confidence (12 emails):
1. [2026-01-06] From: team@company.com | CC: you@gmail.com | Subject: FYI
... [11 more]

Action: Mark as read + Move to Secretary/Auto-Cleaned
Approve this batch? (yes/no)"
```

### Tools That Require This Pattern

| Tool | Subagent | Returns |
|------|----------|---------|
| `quick_clean_inbox` | @bulk-cleaner | Cleanup candidates |
| `triage_priority_emails` | @triage | Priority emails with signals |
| `triage_remaining_emails` | @triage | Remaining emails with signals |

### Anti-Patterns (FORBIDDEN)

❌ **Prompting user after each batch**:
```
# WRONG - Don't do this!
result = quick_clean_inbox()
show_to_user(result["candidates"])  # User sees partial results
user_approves()
result2 = quick_clean_inbox(continuation_state=...)
show_to_user(result2["candidates"])  # User prompted AGAIN
```

❌ **Primary agent running the loop**:
```
# WRONG - Primary agent should delegate, not loop
while has_more:
    result = quick_clean_inbox(...)  # Primary agent shouldn't do this
```

✅ **Correct: Subagent loops, primary agent approves once**:
```
# RIGHT
@secretary delegates to @bulk-cleaner
@bulk-cleaner runs loop internally, returns complete list
@secretary shows complete list to user
User approves once
@secretary executes
```

---

## 🔍 Semantic Search Capabilities (Optional)

When PostgreSQL + pgvector is configured with embeddings enabled, additional AI-powered search capabilities become available.

### Additional Tools (Conditional)

These tools are ONLY available when `database.backend: postgres` AND `database.embeddings.enabled: true`:

| Tool | Classification | Description |
|------|----------------|-------------|
| `semantic_search_emails` | Read-Only ✅ | Search emails by meaning, not keywords |
| `find_related_emails` | Read-Only ✅ | Find emails similar to a reference email |
| `get_embedding_status` | Read-Only ✅ | Check embeddings system health |

### Intelligent Search Routing

Agents SHOULD route search queries intelligently based on query type:

```
IF query has specific criteria (from:, to:, subject:, date range, exact phrase):
    → Use search_emails() or gmail_search() (keyword search)
    
ELSE IF query is conceptual ("emails about budget concerns", "discussions about timeline"):
    → Use semantic_search_emails() (meaning-based search)
    
ELSE IF semantic search unavailable:
    → Fall back to search_emails() with best-effort keywords
```

### Context Gathering Pattern

When drafting replies, agents SHOULD use `find_related_emails` to gather context:

```
1. User asks to reply to email UID 12345
2. Agent calls get_email_details(uid=12345) to read the email
3. Agent calls find_related_emails(uid=12345) to find similar discussions
4. Agent reviews related emails for:
   - Previous commitments made
   - Decisions already taken
   - Relevant context and history
5. Agent drafts reply with full context awareness
6. Agent presents draft to user (standard HITL flow)
```

### Morning Briefing Enhancement

When semantic search is available, the morning briefing can be enhanced:

```
Standard briefing returns high-priority emails
↓
For each high-priority email, optionally call find_related_emails()
↓
Present context: "Sarah's question relates to 3 previous emails about Q4 planning"
```

### Graceful Degradation

If semantic search is NOT configured:
- `semantic_search_emails` → Returns error suggesting `search_emails`
- `find_related_emails` → Returns error explaining embedding not found
- `get_embedding_status` → Always works, shows diagnostic info

Agents MUST handle these errors gracefully and fall back to keyword search.

### Signals from Semantic Search

Semantic search results include a `similarity` score (0.0 to 1.0):
- **> 0.85**: Very high relevance, strong semantic match
- **0.70 - 0.85**: Good relevance, related topic
- **0.50 - 0.70**: Moderate relevance, may be tangentially related
- **< 0.50**: Low relevance (filtered out by default threshold)

Agents MAY use similarity scores to prioritize results or determine confidence.

---

## 🎓 Agent Training Guidelines

When creating agent prompts, always include:
1. Reference to this AGENTS.md file
2. Explicit reminder: "You MUST confirm before any mutation"
3. Example safe interaction flows
4. Tool classification awareness (read-only vs mutation)

---

**Last Updated**: 2026-01-09  
**Enforcement**: All agents (primary + subagents) MUST comply with these rules. Violations will result in agent behavior review and correction.
