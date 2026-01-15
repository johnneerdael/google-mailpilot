# OpenCode Agent Setup Guide

This document provides a complete, copy/paste-ready guide for setting up the **Google MailPilot MCP** agent ecosystem in OpenCode.

## Table of Contents
1. [Project Structure](#project-structure)
2. [Quick Start](#quick-start)
3. [Agent Rules (AGENTS.md)](#agent-rules-agentsmd)
4. [Primary Agent: secretary](#primary-agent-secretary)
5. [Subagents](#subagents)
6. [Commands](#commands)
7. [Example Workflows](#example-workflows)
8. [Best Practices](#best-practices)

---

## Project Structure

The OpenCode agent setup consists of:

```
google-mailpilot/
├── AGENTS.md                          # Hard rules (HITL, confidence gating, etc.)
├── .opencode/
│   ├── agent/
│   │   ├── secretary.md               # Primary orchestrator with mutations (mode: primary)
│   │   ├── secretary-plan.md          # Read-only analysis mode (mode: primary)
│   │   ├── briefer.md                 # Morning briefing specialist (mode: subagent)
│   │   ├── triage.md                  # Email prioritization (mode: subagent)
│   │   ├── bulk-cleaner.md            # Bulk cleanup proposals (mode: subagent)
│   │   ├── email-drafter.md           # Draft specialist (mode: subagent)
│   │   ├── scheduler.md               # Calendar analysis (mode: subagent)
│   │   ├── email-curator.md           # Maintenance proposals (mode: subagent)
│   │   └── document-clerk.md          # Attachment intelligence (mode: subagent)
│   └── command/
│       ├── morning.md                 # /morning briefing command
│       ├── clean-inbox.md             # /clean-inbox bulk cleanup
│       ├── reschedule.md              # /reschedule natural language
│       ├── setup-folders.md           # /setup-folders label init
│       └── vip.md                     # /vip email filter
```

### Two Primary Agents (Tab to Switch)
- **secretary**: Full execution capabilities (mutation tools enabled)
- **secretary-plan**: Read-only analysis mode (mutation tools disabled)

Use Tab key to cycle between them. Use **secretary-plan** for safe analysis, switch to **secretary** when ready to execute.

---

## Quick Start

### 1. Copy Agent Rules
The `AGENTS.md` file in the project root defines hard rules for all agents. **This file already exists** in this repository at `/AGENTS.md`.

**Key Rules**:
- **Human-in-the-Loop (HITL)**: All mutations require explicit user confirmation
- **Bulk Confidence Gating**: High confidence (100 max), medium/low (10 max)
- **Auto-Draft Rule**: Automatically draft replies for questions, never auto-send
- **Timezone Awareness**: Respect configured timezone and working hours
- **Special Circumstances**: Never auto-decline meetings outside hours

### 2. Initialize Secretary Labels
Run once to create the Gmail label hierarchy:
```
/setup-folders
```

This creates:
- `Secretary/Priority`
- `Secretary/Action-Required`
- `Secretary/Processed`
- `Secretary/Calendar`
- `Secretary/Newsletter`
- `Secretary/Waiting`

### 3. Start Using Commands
```
/morning              # Get daily briefing
/clean-inbox          # Bulk cleanup with approval
/reschedule Meeting with Tom to tomorrow at 2pm
/vip                  # Show VIP emails only
```

---

## Agent Rules (AGENTS.md)

The `AGENTS.md` file (already present in this repository) defines project-wide rules. Here are the critical sections:

### Human-in-the-Loop (HITL)

**Mutation tools requiring confirmation**:
- `send_email`, `mark_as_read`, `mark_as_unread`, `move_email`, `modify_gmail_labels`, `process_email`, `create_calendar_event`, `process_meeting_invite`

**Draft-Review-Send Pattern**:
```
1. AI analyzes situation
2. AI prepares draft using create_draft_reply
3. AI presents draft to user with ALL details visible
4. USER reviews and approves: "yes" / "send it" / "looks good"
5. AI executes mutation ONLY after explicit confirmation
```

### Bulk Action Rules (Confidence-Based Gating)

| Confidence | Max Batch | Approval Display |
|------------|-----------|------------------|
| High (>90%) | 100 emails | Date, From, To, CC, Subject (no body) |
| Medium (50-90%) | 10 emails | Date, From, To, CC, Subject + 300-char body |
| Low (<50%) | 10 emails | Date, From, To, CC, Subject + 300-char body |

**Standard Bulk Actions**:
1. `mark_as_read(folder="INBOX", uids=[...])`
2. `modify_gmail_labels(add_labels=["Secretary/Newsletter"], remove_labels=["INBOX"])`
3. Archive (remove INBOX label)

### Auto-Drafting Rule

**Trigger**: Email has `signals.has_question=true` AND user is in `To:` field (not CC)

**Workflow**:
1. Detect incoming email with question directed at user
2. Call `create_draft_reply()` to generate response draft
3. Store draft in Gmail Drafts folder
4. Notify user: "I've drafted a reply to [Sender]. Review in Drafts."
5. **NEVER call `send_email()` without explicit user approval**

### Timezone & Working Hours Rules

All scheduling operations respect `config.yaml` settings:
- `timezone`: IANA timezone (e.g., "America/Los_Angeles")
- `working_hours.start`: "09:00"
- `working_hours.end`: "18:00"
- `working_hours.workdays`: [1, 2, 3, 4, 5] (Monday-Friday)

**Special Circumstances Exception**: Even if meeting is outside working hours, NEVER auto-decline. Present options:
1. Accept as-is (special circumstances)
2. Suggest alternative times within working hours
3. Decline politely

---

## Primary Agent: secretary

**File**: `.opencode/agent/secretary.md` (exec mode) and `.opencode/agent/secretary-plan.md` (read-only mode)

### Two Modes
1. **secretary** - Full execution capabilities (mutation tools enabled)
2. **secretary-plan** - Analysis only (mutation tools disabled)

Use **Tab** key to cycle between them.

### Role
Primary orchestrator for all Gmail + Google Calendar workflows. Delegates to specialized subagents.

### Key Permissions
```yaml
permission:
  task:
    briefer: allow
    triage: allow
    bulk-cleaner: allow
    email-drafter: allow
    scheduler: allow
    email-curator: allow
    document-clerk: allow
```

### Tool Access
- **Read-only**: `get_daily_briefing`, `gmail_search`, `gmail_get_thread`, `summarize_thread`, `get_calendar_availability`, `list_calendar_events`
- **Mutations** (enabled in `tools:`, HITL enforced via prompt): `send_email`, `modify_gmail_labels`, `process_email`, `mark_as_read`, `create_calendar_event`

### Important: OpenCode Tool Permission Format
In OpenCode agent frontmatter, **`tools:` only accepts boolean values** (`true` or `false`):
```yaml
tools:
  gmail_search: true
  send_email: true  # Enabled (not "ask")
```

The string value `"ask"` is **NOT valid** for MCP tools. It only works for OpenCode's built-in tools (`edit`, `bash`, `webfetch`) under the `permission:` section:
```yaml
permission:
  edit: ask
  bash: ask
```

For MCP mutation tools (like Gmail/Calendar operations), HITL is enforced via:
1. **Prompt instructions** (AGENTS.md rules)
2. **Architecture**: Subagents have mutation tools set to `false`, only primary agent can execute

### Usage
The `secretary` agent is invoked automatically when you use OpenCode chat or run commands like `/morning`, `/clean-inbox`.

---

## Subagents

### @briefer - Morning Briefing Specialist
**File**: `.opencode/agent/briefer.md`

**Purpose**: Generate daily intelligence digest with prioritized action items.

**Core Tool**: `get_daily_briefing(date)`

**Output Format**:
```
Good morning! Here's your briefing for Wednesday, Jan 8:

📅 CALENDAR (3 events today):
- 10:00 AM: Team Sync (Google Meet link)
- 2:00 PM: Product Review with Sarah

📧 EMAIL PRIORITY BREAKDOWN:
🚨 CRITICAL (2 emails):
- From: CEO | Subject: Q1 Budget Approval Needed EOD

⚠️ IMPORTANT (5 emails):
- From: Boss | Subject: Weekly Status Report Due Friday

📧 NORMAL (12 emails)
📰 LOW PRIORITY (8 newsletters)
```

**Invocation**: Automatically triggered by `/morning` command or manual request to @secretary.

---

### @bulk-cleaner - Autonomous Bulk Cleanup
**File**: `.opencode/agent/bulk-cleaner.md`

**Purpose**: Autonomously gather ALL cleanup candidates using time-boxed continuation, then return complete results for approval. **Does not execute mutations** (proposals only).

**Architecture Note**: This subagent has mutation tools set to `false`. It runs the continuation loop autonomously and returns the complete aggregated list to the primary **secretary** agent for user approval and execution.

**CRITICAL: Autonomous Continuation Loop**

The `quick_clean_inbox` tool is time-boxed (5s per call) to avoid MCP timeouts. The @bulk-cleaner subagent MUST:

1. **Call `quick_clean_inbox()`** without continuation_state to start
2. **If `has_more=true`**, automatically call again with `continuation_state` from response
3. **Repeat** until `status="complete"` or `has_more=false`
4. **Aggregate ALL candidates** from all batches into a single list
5. **Return complete results** to @secretary (NOT partial results)
6. **NEVER prompt user** during the continuation loop

```python
# Subagent internal loop (pseudo-code)
all_candidates = []
continuation_state = None

while True:
    result = quick_clean_inbox(continuation_state=continuation_state)
    all_candidates.extend(result["candidates"])
    
    if result["status"] == "complete" or not result["has_more"]:
        break
    continuation_state = result["continuation_state"]

# Return aggregated results to primary agent
return {"total": len(all_candidates), "candidates": all_candidates}
```

**Why This Pattern?**
- Each batch completes in ~5s (never hits MCP timeout)
- User sees COMPLETE picture before approving (not partial every 5s)
- Single approval prompt at the end
- Subagent handles complexity; primary agent stays simple

**Confidence Detection Patterns**:

**High Confidence (>90%)**:
- From: `no-reply@`, `newsletter@`, `automated@`
- Subject: "weekly digest", "monthly report", "unsubscribe"
- Labels: `CATEGORY_PROMOTIONS`

**Medium Confidence (50-90%)**:
- User in `CC:` only (not `To:`)
- Internal domain, older than 7 days
- No VIP sender, no question marks

**Low Confidence (<50%)**:
- Ambiguous cases requiring human judgment

**Approval Prompt Example** (after autonomous collection):
```
I've identified 47 newsletter emails with high confidence (>90%). Review and approve:

1. [2026-01-07] From: newsletter@company.com | To: you@gmail.com | Subject: Weekly Digest #234
2. [2026-01-07] From: no-reply@github.com | To: you@gmail.com | Subject: Repository Activity
... [45 more emails]

Action: Mark as read + Apply label "Secretary/Newsletter" + Archive
Approve this batch? (yes/no/show-details)
```

**Invocation**: `/clean-inbox` command.

---

### @email-drafter - Draft Specialist (Never Sends)
**File**: `.opencode/agent/email-drafter.md`

**Purpose**: Create contextual email drafts. **NEVER sends emails.**

**Critical Rule**: This agent MUST NEVER call `send_email()` under any circumstances. It only creates drafts using `create_draft_reply()`.

**Auto-Draft Trigger**:
- Email has `signals.has_question=true`
- User is in `To:` field (not CC)

**Workflow**:
1. Call `gmail_get_thread(thread_id)` for full context
2. Analyze conversation tone and history
3. Check attachments if present
4. Create draft using `create_draft_reply()`
5. Notify: "Draft created for [Sender]. Preview: [first 200 chars]"
6. Wait for explicit approval to send (via @secretary)

**Example**:
```
User: "Draft a reply to Sarah's email"
@email-drafter: [Reads full thread]
@email-drafter: "I've drafted a reply to Sarah:
                 
                 Subject: Re: Q1 Budget Timeline
                 
                 Hi Sarah,
                 
                 Thanks for your question. Based on our last discussion,
                 we're targeting approval by Jan 15th. I'll have the final
                 numbers ready by EOD today.
                 
                 Best regards,
                 [Your name]
                 
                 This draft is saved in your Drafts folder. Send it? (ask @secretary)"
```

---

### @scheduler - Calendar & NL Reschedule
**File**: `.opencode/agent/scheduler.md`

**Purpose**: Calendar analysis, meeting coordination, natural language rescheduling. **Does not execute mutations** (proposals only).

**Architecture Note**: This subagent has mutation tools (`create_calendar_event`, `process_meeting_invite`) set to `false`. It analyzes calendar and returns proposals to the primary **secretary** agent for execution.

**Natural Language Reschedule Workflow**:

**Input**: `/reschedule Meeting today with Tom to tomorrow at 10am`

**Steps**:
1. Parse: attendee="Tom", current_date=today, new_date=tomorrow, new_time=10am
2. Call `list_calendar_events(time_min=today_start, time_max=today_end)` to find matching event
3. If multiple matches, ask: "I found 2 meetings with Tom today. Which one?"
4. Call `suggest_reschedule(thread_id, suggested_date="2026-01-09")`
   - Automatically respects `working_hours` and `workdays`
   - Returns 3 alternative slots if 10am is busy
5. Draft reschedule email using `create_draft_reply()`
6. Wait for user approval

**Special Circumstances Handling**:
```
If proposed time is outside working hours:
"10 PM is outside your working hours (9 AM - 6 PM). Would you like to:
 1. Suggest 10 PM anyway (special circumstances)
 2. Find alternatives within working hours
 3. Cancel reschedule"
```

**Invocation**: `/reschedule $ARGUMENTS` command or direct request to @secretary.

---

### @email-curator - Routine Maintenance
**File**: `.opencode/agent/email-curator.md`

**Purpose**: Identify routine inbox maintenance candidates and propose organization. **Does not execute mutations** (proposals only).

**Architecture Note**: This subagent has mutation tools set to `false`. It identifies maintenance candidates and returns proposals to the primary **secretary** agent for execution.

**Targets**:
- Internal CC-only emails
- Automated/bulk mail (Jira, GitHub, CI/CD)
- Old processed threads

**Attachment Screening**: Before proposing archival of newsletters, checks for important attachments (invoices, reports) and alerts user.

---

### @document-clerk - Attachment Intelligence
**File**: `.opencode/agent/document-clerk.md`

**Purpose**: Extract intelligence from email attachments (PDF, DOCX, TXT, LOG, MD).

**Document Type Workflows**:
- **Invoices**: Extract vendor, amount, due date → create task
- **Roadmaps**: Extract Q1/Q2 milestones → summarize
- **Server Logs**: Find ERROR/CRITICAL events → alert
- **Meeting Notes**: Extract action items → create tasks
- **Contracts**: Extract key terms, deadlines, signature requirements

**Example**:
```
User: "What's in the invoice attachment?"
@document-clerk: [Reads invoice.pdf]
@document-clerk: "Invoice Analysis:
                  - Vendor: Acme Corp
                  - Amount: $5,000
                  - Due: Jan 15, 2026
                  - Task created: 'Pay Invoice #1234'"
```

---

## Commands

### /morning - Morning Briefing
**File**: `.opencode/command/morning.md`

**Usage**: `/morning`

**What it does**:
1. Calls `get_daily_briefing(date=today)`
2. Analyzes email_candidates signals (VIP, deadline, question, meeting)
3. Lists calendar events
4. Presents prioritized action plan

**Output**: Structured briefing with calendar, critical emails, important emails, normal emails, low-priority count.

---

### /clean-inbox - Automatic Inbox Cleanup (Autonomous Loop)
**File**: `.opencode/command/clean-inbox.md`

**Usage**: `/clean-inbox`

**What it does**:
1. Delegates to @bulk-cleaner subagent
2. @bulk-cleaner runs autonomous continuation loop:
   - Calls `quick_clean_inbox()` (processes for 5s, returns partial)
   - If `has_more=true`, automatically calls again with `continuation_state`
   - Repeats until `status="complete"` or `has_more=false`
   - Aggregates ALL candidates from all batches
3. @bulk-cleaner returns complete aggregated list to @secretary
4. @secretary presents complete list to user for approval
5. User approves → @secretary calls `execute_clean_batch(uids=[...])`

**Safety Guarantees**:
- Only identifies emails where user is **NOT** in To: or CC: fields
- Only identifies emails where user's email/name is **NOT** mentioned in body
- Emails are moved (not deleted) - fully recoverable to `Secretary/Auto-Cleaned`
- Time-boxed (5s per batch) prevents MCP timeout
- **Single approval prompt** after ALL data is gathered (not every 5 seconds)

**Example Output**:
```
Processed 145 unread emails across 3 batches:
- Cleanup candidates: 47 emails
- Skipped: 98 emails (you were addressed)

High Confidence (35 emails):
1. From: newsletter@company.com | Subject: Weekly Digest
2. From: no-reply@github.com | Subject: Repository Activity
...

Action: Mark as read + Move to Secretary/Auto-Cleaned
Approve this batch? (yes/no)
```

---

### /triage-priority - High-Priority Email Triage (Autonomous Loop)
**File**: `.opencode/command/triage-priority.md`

**Usage**: `/triage-priority`

**What it does**:
1. Delegates to @triage subagent
2. @triage runs autonomous continuation loop with `triage_priority_emails` tool
3. Aggregates all priority emails across batches
4. Returns complete list to @secretary for presentation

**Priority Criteria**:
- User in To: with <5 recipients, OR
- User in To: with <15 recipients AND first/last name in body

**Output**: Priority emails with sender, subject, priority reason, content summary, and suggested action (reply, schedule, FYI).

---

### /triage-remaining - Process Remaining Emails (Autonomous Loop)
**File**: `.opencode/command/triage-remaining.md`

**Usage**: `/triage-remaining`

**What it does**:
1. Delegates to @triage subagent
2. @triage runs autonomous continuation loop with `triage_remaining_emails` tool
3. Aggregates all remaining emails across batches
4. Returns complete list to @secretary for presentation

**Output**: Emails grouped by action (Read Later, Review This Week, Needs Response, Calendar Check).

---

### /reschedule - Natural Language Reschedule
**File**: `.opencode/command/reschedule.md`

**Usage**: `/reschedule $ARGUMENTS`

**Examples**:
```
/reschedule Meeting today with Tom to tomorrow at 10am
/reschedule Team sync to Friday afternoon
/reschedule 1-on-1 with Sarah to next week
```

**What it does**:
1. Parses natural language (attendee, current date, new date/time)
2. Searches calendar for matching event
3. Checks availability and working hours
4. Drafts reschedule email
5. Waits for approval

**Special**: If outside working hours, presents options (never auto-declines).

---

### /setup-folders - Initialize Labels
**File**: `.opencode/command/setup-folders.md`

**Usage**: `/setup-folders`

**What it does**: Calls `setup_smart_labels()` to create `Secretary/*` label hierarchy (idempotent operation).

---

### /vip - Show VIP Emails
**File**: `.opencode/command/vip.md`

**Usage**: `/vip`

**What it does**:
1. Calls `get_daily_briefing()`
2. Filters for `signals.is_from_vip=true`
3. Presents list with signals (has_question, mentions_deadline, mentions_meeting)

---

## Example Workflows

### Workflow 1: Morning Routine
```
User: /morning

@secretary: [Delegates to @briefer]
@briefer: [Calls get_daily_briefing()]
@briefer: "Good morning! Here's your briefing for Wednesday, Jan 8:
          
          📅 CALENDAR (3 events):
          - 10 AM: Team Sync
          - 2 PM: Product Review with Sarah
          - 4 PM: 1-on-1 with Boss
          
          📧 EMAIL PRIORITY:
          🚨 CRITICAL (2 emails):
          - From: CEO | Subject: Q1 Budget Approval Needed EOD
          - From: Lead Client | Subject: Can we reschedule demo?
          
          ⚠️ IMPORTANT (5 emails):
          - From: Boss | Subject: Weekly Status Due Friday
          ...
          
          💬 AUTO-DRAFT READY:
          I've drafted replies for 2 emails with questions.
          Review in Drafts folder."
```

---

### Workflow 2: Automatic Inbox Cleanup (Autonomous Loop)
```
User: /clean-inbox

@secretary: [Delegates to @bulk-cleaner]

@bulk-cleaner: [Starts autonomous continuation loop]
  → Calls quick_clean_inbox() - processes batch 1 (5s)
  → has_more=true, calls again with continuation_state
  → Calls quick_clean_inbox(continuation_state=...) - batch 2 (5s)
  → has_more=true, continues...
  → Calls quick_clean_inbox(continuation_state=...) - batch 3 (5s)
  → has_more=false, aggregates ALL results
  → Returns complete list to @secretary

@secretary: [Receives complete aggregated results]
@secretary: "✅ Inbox analysis complete!
             
             Processed 145 unread emails across 3 batches:
             - Cleanup candidates: 47 emails
             - Skipped: 98 emails (you were addressed)
             
             High Confidence (35 emails):
             1. From: newsletter@company.com | Subject: Weekly Digest
             2. From: no-reply@github.com | Subject: Repository Activity
             ... [33 more]
             
             Medium Confidence (12 emails):
             1. From: team@company.com | CC: you@gmail.com | Subject: FYI
             ... [11 more]
             
             Action: Mark as read + Move to Secretary/Auto-Cleaned
             Approve this batch? (yes/no)"

User: yes

@secretary: [Calls execute_clean_batch(uids=[...all 47 UIDs...])]
@secretary: "✅ 47 emails moved to Secretary/Auto-Cleaned"
```

**Key Points**:
- @bulk-cleaner runs the continuation loop **autonomously** (no user prompts during gathering)
- User sees **complete results** after ALL batches are processed
- Single approval prompt at the end (not every 5 seconds)
- Only after approval does @secretary call `execute_clean_batch()`

---

### Workflow 3: Auto-Draft Question
```
[New email arrives from Sarah with question: "Can you review the contract by EOD?"]

@secretary: [Detects signals.has_question=true, user in To: field]
@secretary: [Delegates to @email-drafter]
@email-drafter: [Calls gmail_get_thread to read full context]
@email-drafter: [Creates draft using create_draft_reply]
@email-drafter: "📧 Auto-drafted reply for Sarah:
                 
                 Subject: Re: Contract Review
                 
                 Hi Sarah,
                 
                 I'll review the contract and send you my feedback by EOD today.
                 
                 Best regards,
                 [Your name]
                 
                 Draft saved in your Drafts folder. Send it? (yes/no)"

User: yes

@secretary: [Confirms user approval]
@secretary: [Calls send_email with draft content]
@secretary: "✅ Email sent to Sarah."
```

---

### Workflow 4: Natural Language Reschedule
```
User: /reschedule Meeting today with Tom to tomorrow at 2pm

@secretary: [Delegates to @scheduler]
@scheduler: [Calls list_calendar_events for today]
@scheduler: [Finds "1-on-1 with Tom" at 3 PM today]
@scheduler: [Calls suggest_reschedule(thread_id, "2026-01-09")]
@scheduler: [Checks: 2 PM is within working hours (9 AM - 6 PM) and available]
@scheduler: "I'll reschedule your 1-on-1 with Tom from today 3 PM to tomorrow 2 PM.
             
             Draft email:
             'Hi Tom,
             
             I need to reschedule our 1-on-1 from today at 3 PM to tomorrow at 2 PM.
             Does that work for you?
             
             Best regards,
             [Your name]'
             
             Send this and update calendar? (yes/no)"

User: yes

@scheduler: [Calls send_email + create_calendar_event]
@scheduler: "✅ Meeting rescheduled to tomorrow 2 PM. Email sent to Tom."
```

---

### Workflow 5: Meeting Outside Working Hours
```
User: "Accept the meeting invite from London team at 8 PM"

@secretary: [Delegates to @scheduler]
@scheduler: [Finds meeting invite]
@scheduler: [Detects 8 PM is outside working_hours: 9 AM - 6 PM]
@scheduler: "This meeting is at 8 PM, outside your configured working hours (9 AM - 6 PM).
             
             This might be necessary for international coordination. Would you like to:
             1. Accept as-is (special circumstances)
             2. Suggest alternative times within your working hours (may not work for London timezone)
             3. Decline
             
             What would you prefer?"

User: 1

@scheduler: [Calls process_meeting_invite to accept]
@scheduler: "✅ Meeting accepted at 8 PM (outside normal hours)."
```

---

## Best Practices

### 1. Start Every Session with Setup
Run `/setup-folders` once to initialize label hierarchy.

### 2. Use /morning Daily
Make `/morning` your first command each day to get situational awareness.

### 3. Trust the Confidence Gating
The @bulk-cleaner uses pattern matching to classify emails. High-confidence batches (>90%) are safe for bulk approval.

### 4. Review Auto-Drafts Promptly
When @email-drafter creates auto-drafts, review them in your Drafts folder. Edit if needed, then ask @secretary to send.

### 5. Configure VIPs in config.yaml
Add important sender domains to `vip_senders` list in `config.yaml`:
```yaml
vip_senders:
  - ceo@company.com
  - boss@company.com
  - leadclient.com
```

### 6. Use Natural Language for Reschedule
Instead of looking up event IDs, use natural language:
```
/reschedule meeting with Tom tomorrow at 10am
```

### 7. Leverage Timezone Awareness
All scheduling respects your configured timezone and working hours. No need for manual time conversion.

### 8. Safety First
- Agents will **always** confirm before mutations
- If unsure, they'll ask clarifying questions
- You can always say "no" or "cancel"

---

## Troubleshooting

### "Agent not found" error
Ensure `.opencode/agent/*.md` files exist and have correct `mode:` field (primary for secretary, subagent for others).

### "Tool not available" error
Check that the tool name matches exactly what's in `workspace_secretary/tools.py`. Tool names are case-sensitive.

### Bulk cleanup not respecting confidence limits
Review `@bulk-cleaner` implementation. It should enforce:
- High confidence: max 100 per batch
- Medium/Low confidence: max 10 per batch

### Auto-draft not triggering
Verify:
1. Email has `signals.has_question=true` (check `get_daily_briefing` output)
2. User is in `To:` field (not just CC)
3. @email-drafter is allowed in secretary's `permission.task`

### Reschedule can't find meeting
@scheduler searches by attendee name. If "Tom" doesn't match, try full name or email domain.

---

## Summary

You now have a complete OpenCode agent ecosystem for intelligent Gmail + Google Calendar management with:

✅ **Hard safety rules** (HITL, confidence gating, auto-draft workflow)  
✅ **Primary orchestrator** (secretary) with 7 specialized subagents  
✅ **5 slash commands** for common workflows  
✅ **Timezone-aware scheduling** with working hours respect  
✅ **Natural language reschedule** (no event IDs required)  
✅ **Bulk cleanup** with confidence-based approval UX  
✅ **Auto-drafting** for questions (never auto-sends)  

Copy the agent and command files from this repository's `.opencode/` directory, ensure `AGENTS.md` is in the root, and start using `/morning` and `/clean-inbox` to supercharge your email productivity!
