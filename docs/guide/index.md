# Guide

Welcome to **Google Workspace Secretary MCP** — an AI-native Gmail client exposed as MCP tools, built around safe automation primitives.

::: tip What This Is
**Secretary MCP is not an IMAP library.** It's a workflow engine for AI assistants that provides:
- **Signals** for intelligent reasoning (VIP detection, deadline mentions, questions)
- **Staged mutations** with human approval (draft-review-send pattern)
- **Time-boxed batch operations** that never timeout
- **Optional semantic search** via pgvector embeddings

The underlying IMAP/SMTP protocols are implementation details—you interact with purpose-built secretary workflows.
:::

## What Makes This Unique

| Traditional Email SDK | Secretary MCP |
|----------------------|---------------|
| Returns raw messages | Returns **signals** (`is_from_vip`, `has_question`, `mentions_deadline`) |
| You handle timeouts | **Time-boxed operations** with continuation states |
| Direct mutations | **Human-in-the-loop** confirmation for all changes |
| Keyword search only | **Semantic search** finds emails by meaning |
| Generic IMAP support | **Gmail-optimized** with labels, threading, OAuth |

## Getting Started

New to Secretary MCP? Start here:

1. [Installation](/getting-started) - Docker setup with OAuth authentication
2. [Configuration](./configuration) - Gmail settings, VIP senders, working hours
3. [Docker Deployment](./docker) - Production deployment with persistence
4. [Security](./security) - Bearer auth and SSL configuration

## Core Concepts

### Signals, Not Decisions

Tools return **structured signals** for AI reasoning—they don't make decisions for you:

| Signal | Meaning |
|--------|---------|
| `is_from_vip` | Sender matches your configured VIP list |
| `has_question` | Email contains questions or requests |
| `mentions_deadline` | Contains urgency keywords (EOD, ASAP, urgent) |
| `mentions_meeting` | Contains scheduling language |
| `is_addressed_to_me` | Your email is in the To: field |

The **AI decides priority** based on context. An "urgent" email from a vendor at 5 PM Friday might be less important than a calm question from your CEO Monday morning.

### Human-in-the-Loop Safety

All mutation operations require explicit user confirmation:

```
User: "Reply to Sarah saying I'll attend"

AI: ❌ Does NOT send immediately
AI: ✅ Creates draft, shows it to user:

    To: sarah@company.com
    Subject: Re: Team Meeting
    
    Hi Sarah,
    I'll be there!
    
    Send this email? (yes/no)

User: "yes"
AI: ✅ Now sends the email
```

**Mutation tools** (`send_email`, `move_email`, `modify_labels`) always require confirmation.
**Staging tools** (`create_draft_reply`) are safe—they prepare but don't execute.

### Time-Boxed Batch Operations

Large inboxes don't cause timeouts. Batch tools use **continuation states**:

```python
# First call - processes for ~5 seconds, returns partial results
result = quick_clean_inbox()
# {"status": "partial", "has_more": true, "continuation_state": "...", "candidates": [...]}

# Continue where you left off
result = quick_clean_inbox(continuation_state=result["continuation_state"])
# {"status": "complete", "has_more": false, "candidates": [...]}
```

This pattern works for `quick_clean_inbox`, `triage_priority_emails`, and `triage_remaining_emails`.

### Timezone-Aware Scheduling

All calendar operations respect your configured:
- **timezone**: IANA format (e.g., `Europe/Amsterdam`)
- **working_hours**: Start/end times and workdays

Meeting suggestions only occur within your working hours—but agents always ask before declining out-of-hours meetings (you might have exceptions).

## Building AI Agents

Learn to build intelligent secretary workflows:

- [Agent Patterns](./agents) - Morning Briefing, Triage, Scheduling patterns
- [Use Cases](./use-cases) - Real-world examples
- [Semantic Search](./semantic-search) - AI-powered email search with pgvector

## Quick Reference

### Configuration (Required Fields)

| Field | Description |
|-------|-------------|
| `identity.email` | Your Gmail address |
| `imap.host` | `imap.gmail.com` |
| `timezone` | IANA timezone (e.g., `America/Los_Angeles`) |
| `working_hours` | Start, end, workdays |
| `vip_senders` | Priority email addresses (or `[]` if none) |

See [Configuration](./configuration) for complete reference.

### Common Tasks

| Task | How |
|------|-----|
| Daily Briefing | "Give me my morning briefing" |
| Triage Inbox | "Scan my unread emails and prioritize VIPs" |
| Check Availability | "Am I free tomorrow at 2 PM?" |
| Find Document | "Find the invoice PDF from Accounting" |
| Draft Reply | "Draft a reply saying I'll review by EOD" |
| Bulk Cleanup | "Clean up my newsletters and notifications" |

## Next Steps

1. [Configure your server](./configuration) with Gmail settings
2. Learn [Agent Patterns](./agents) for intelligent workflows  
3. Explore the [MCP Tools Reference](/api/) for all available tools
4. Set up [Semantic Search](./semantic-search) for meaning-based email search

---

**Questions?** Check [Use Cases](./use-cases) or [open an issue](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP/issues).
