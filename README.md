# Google Workspace Secretary MCP

Google Workspace Secretary MCP is an AI-native Model Context Protocol (MCP) server that transforms your Google Workspace (Gmail, Calendar) and email inboxes into a searchable, programmable knowledge base for Claude and other AI assistants.

## 🚀 Overview

The Google Workspace Secretary MCP server enables AI assistants to act as intelligent email and calendar secretaries. Unlike simple email clients, this server is optimized for high-density AI analysis, document processing, and advanced calendar management with **timezone-aware scheduling** and **intelligent email prioritization**.

### The "Smart Secretary" Framework
The server includes tools that scaffold a standardized organization hierarchy:
- **Triage**: Intelligent discovery of new work with priority signals.
- **Context**: Deep understanding of email threads and documents.
- **Action**: Managing calendar invites and drafting professional replies.

### Key Capabilities
- **Google Workspace Native**: Full support for Gmail Labels, Thread IDs, and Google Calendar events.
- **Intelligent Email Prioritization**: Daily briefings with AI-ready signals (VIP senders, urgency markers, questions detected).
- **Timezone-Aware Scheduling**: All calendar operations respect your configured timezone and working hours.
- **AI-Optimized Triage**: Fetch bulk unseen emails with critical context (To/CC/BCC) and truncated bodies (700 chars) for fast, token-efficient analysis.
- **Document Intelligence**: Deep-dive into attachments. Extract text from **PDF**, **DOCX**, and log files directly into the AI's context.
- **Advanced Search**: Natural-language friendly multi-criteria search.
- **Calendar Orchestration**: Automatically check availability, parse invites, and suggest meeting times within your working hours.

## ⚙️ Configuration

Google Workspace Secretary MCP requires a `config.yaml` file with the following structure:

### Required Configuration

```yaml
# IMAP/Gmail Configuration
imap:
  host: imap.gmail.com
  port: 993
  username: your-email@gmail.com
  use_ssl: true
  oauth2:  # Recommended for Gmail
    client_id: YOUR_CLIENT_ID.apps.googleusercontent.com
    client_secret: YOUR_CLIENT_SECRET

# Timezone (IANA format: America/Los_Angeles, Europe/London, Asia/Tokyo)
timezone: America/Los_Angeles

# Working Hours (HH:MM format, 24-hour clock)
working_hours:
  start: "09:00"
  end: "17:00"
  workdays: [1, 2, 3, 4, 5]  # 1=Monday, 7=Sunday

# VIP Senders (exact email addresses for priority flagging)
vip_senders:
  - boss@company.com
  - ceo@company.com
```

### Optional Configuration

```yaml
# Restrict folder access (if omitted, all folders are accessible)
allowed_folders:
  - INBOX
  - Sent
  - Archive

# Calendar configuration
calendar:
  enabled: true
  verified_client: your-email@gmail.com
```

### Environment Variables

All configuration fields can also be set via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `IMAP_HOST` | IMAP server hostname | - |
| `IMAP_PORT` | IMAP server port | `993` |
| `IMAP_USERNAME` | Email username | - |
| `IMAP_PASSWORD` | IMAP password or app-specific password | - |
| `IMAP_USE_SSL` | Use SSL/TLS | `true` |
| `WORKSPACE_TIMEZONE` | IANA timezone string | `UTC` |
| `WORKING_HOURS_START` | Start time (HH:MM) | `09:00` |
| `WORKING_HOURS_END` | End time (HH:MM) | `17:00` |
| `WORKING_HOURS_DAYS` | Workdays (comma-separated: 1-7) | `1,2,3,4,5` |
| `VIP_SENDERS` | Comma-separated email addresses | - |
| `IMAP_ALLOWED_FOLDERS` | Comma-separated folder names | - |

**Example with environment variables:**
```bash
export WORKSPACE_TIMEZONE="America/New_York"
export WORKING_HOURS_START="08:00"
export WORKING_HOURS_END="18:00"
export VIP_SENDERS="boss@company.com,ceo@company.com"
```

## 🛠️ Deployment (Recommended)

The easiest way to run the Google Workspace Secretary MCP server is via Docker Compose.

### Docker Compose
Create a `docker-compose.yaml` file:

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/google-workspace-secretary-mcp:latest
    ports:
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config/config.yaml
      - ./credentials.json:/app/credentials.json
    environment:
      - WORKSPACE_TIMEZONE=America/Los_Angeles
      - WORKING_HOURS_START=09:00
      - WORKING_HOURS_END=17:00
      - VIP_SENDERS=boss@company.com,ceo@company.com
    restart: always
```

See [docs/DOCKER_GUIDE.md](docs/DOCKER_GUIDE.md) for detailed setup instructions.

## 🤖 AI Usage Examples

Once connected, you can ask your AI assistant to perform complex workflows using natural language:

- **Daily Briefing**: "Give me my daily briefing - what emails need my attention today?"
- **Intelligent Triage**: "Scan my last 20 unread emails. Prioritize any from VIPs, urgent requests, or questions that need responses."
- **Smart Scheduling**: "I received a meeting invite from John for tomorrow at 2 PM. Check my calendar and if I'm within my working hours and free, draft a polite acceptance."
- **Timezone-Aware Rescheduling**: "Sarah wants to reschedule our meeting. Suggest 3 alternative times next week during my working hours."
- **Document Analysis**: "Find the invoice PDF sent by 'Accounting' last week, read it, and create a task for the total amount."

## 🧰 Available Tools

### Email & Search Tools

| Tool | Focus | Description |
| :--- | :--- | :--- |
| **`get_unread_messages`** | Analysis | Fetches recent unread emails with snippet and basic headers. |
| **`search_emails`** | Discovery | Search using string, list, or advanced criteria. |
| **`get_email_details`** | Discovery | Fetches full email content, headers, and attachment metadata. |
| **`get_attachment_content`** | Discovery | Extracts text from PDF, DOCX, TXT, and LOG attachments. |
| **`get_thread`** | Context | Retrieves full email thread with all messages. |
| **`summarize_thread`** | Analysis | Provides structured summary of conversation thread. |

### Intelligence & Triage Tools

| Tool | Focus | Description |
| :--- | :--- | :--- |
| **`get_daily_briefing`** | **Intelligence** | Returns calendar events + email candidates with 5 priority signals for LLM-based prioritization. **NEW** |

**Email Priority Signals** (computed per candidate):
- `is_important`: Has Gmail IMPORTANT label
- `is_from_vip`: Sender is in your configured VIP list
- `has_question`: Contains "?" or polite requests (can you, could you, please, would you)
- `mentions_deadline`: Keywords like EOD, ASAP, urgent, deadline, due date
- `mentions_meeting`: Keywords like meet, meeting, schedule, calendar, invite, Zoom, Google Meet

### Calendar Tools

| Tool | Focus | Description |
| :--- | :--- | :--- |
| **`check_calendar`** | Calendar | Lists calendar events for a specific time range (timezone-aware). |
| **`suggest_reschedule`** | **Scheduling** | Suggests 3 meeting slots on target date within your working hours. **NEW** |
| **`process_meeting_invite`** | Workflow | Automatically identifies invites, checks calendar availability, and drafts an appropriate reply. |

### Action Tools (⚠️ Human-in-the-Loop Required)

| Tool | Focus | Safety | Description |
| :--- | :--- | :--- | :--- |
| **`create_draft_reply`** | Action | ✅ Safe | Creates a MIME-formatted draft reply with proper threading. |
| **`send_email`** | **Action** | ⚠️ **HITL** | Sends an email via Gmail API. **Requires explicit user confirmation.** |
| **`process_email`** | Action | ⚠️ **HITL** | Moves/marks/deletes emails. **Requires explicit user confirmation for destructive operations.** |

## 🤝 Building Your AI Assistant

Google Workspace Secretary MCP is designed to support agentic workflows. See [docs/AGENTS.md](docs/AGENTS.md) for detailed patterns and examples.

### Example Agent Patterns

**Morning Briefing Agent:**
```
1. Call get_daily_briefing() for today
2. Analyze email_candidates using the 5 priority signals
3. Summarize: VIP emails, urgent items, questions needing response
4. Present to user with recommended actions
```

**Auto-Scheduler Agent:**
```
1. Monitor inbox for meeting invite keywords
2. Call get_email_details() to read invite
3. Call check_calendar() to verify availability
4. If free during working_hours:
   - Call create_draft_reply() with acceptance
   - Ask user to review before sending
```

**VIP Monitor Agent:**
```
1. Call get_daily_briefing()
2. Filter email_candidates where is_from_vip=true
3. For each VIP email:
   - Call summarize_thread() if part of ongoing conversation
   - Alert user with context and suggested response
```

See [docs/USE_CASES.md](docs/USE_CASES.md) for more examples.

## 🔒 Security & Safety

### Authentication
- **OAuth2**: Secure authentication with Google Workspace (recommended).
- **App Passwords**: Fallback support for IMAP/SMTP with App-Specific Passwords.
- **Bearer Tokens**: Secure your MCP connection using a secret token.

### Human-in-the-Loop (HITL) Safety
All **mutation tools** (send_email, process_email with delete/move) are marked with **CRITICAL SAFETY** warnings in their descriptions. Your AI assistant should:
1. **Always confirm** with the user before calling these tools
2. Show the exact action to be taken (email content, destination folder, etc.)
3. Wait for explicit user approval ("yes", "confirm", "send it")

**Example Safe Interaction:**
```
User: "Draft a reply to John's email"
AI: [Calls create_draft_reply()] "I've created a draft reply. Here's the content: [shows draft]. Would you like me to send it?"
User: "Yes, send it"
AI: [Calls send_email()] "Email sent successfully!"
```

## 📊 Migration Guide

If you're upgrading from an earlier version, note these **breaking changes**:

### Required Config Fields (v0.2.0+)
Three new fields are now **required** in `config.yaml`:
- `timezone` - IANA timezone string (e.g., "America/Los_Angeles")
- `working_hours` - Start/end times and workdays
- `vip_senders` - List of priority email addresses (can be empty list)

**Quick Migration:**
```yaml
# Add these to your existing config.yaml:
timezone: America/Los_Angeles  # Your timezone
working_hours:
  start: "09:00"
  end: "17:00"
  workdays: [1,2,3,4,5]
vip_senders: []  # Start with empty list, add important contacts later
```

**Or use environment variables with defaults:**
```bash
# Defaults to UTC, 9-5 M-F if not specified
docker-compose up -d
```

### Tool Changes
- `get_daily_briefing`: Now returns `email_candidates` (with signals) instead of `priority_emails`
- `suggest_reschedule`: Now timezone-aware and respects working_hours
- Both tools require the new config fields

---

Built with the [Model Context Protocol](https://modelcontextprotocol.io/)

GitHub: [https://github.com/johnneerdael/Google-Workspace-Secretary-MCP](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP)
