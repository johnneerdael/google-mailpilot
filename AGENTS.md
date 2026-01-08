# Agent Rules for Google Workspace Secretary

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

## 📁 Gmail-Only Architecture

This system is designed exclusively for **Gmail + Google Calendar** via Google Workspace APIs.

### Supported Operations
- Gmail API for email (`gmail_search`, `gmail_get_thread`, `modify_gmail_labels`)
- Google Calendar API for scheduling (`get_calendar_availability`, `create_calendar_event`)
- Smart Labels: `Secretary/Priority`, `Secretary/Action-Required`, `Secretary/Processed`, `Secretary/Calendar`, `Secretary/Newsletter`, `Secretary/Waiting`

### Not Supported
- Generic IMAP flows (legacy `search_emails` exists but prefer `gmail_search`)
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

---

## 🎓 Agent Training Guidelines

When creating agent prompts, always include:
1. Reference to this AGENTS.md file
2. Explicit reminder: "You MUST confirm before any mutation"
3. Example safe interaction flows
4. Tool classification awareness (read-only vs mutation)

---

**Last Updated**: 2026-01-08  
**Enforcement**: All agents (primary + subagents) MUST comply with these rules. Violations will result in agent behavior review and correction.
