# IMAP MCP Server

An AI-native Model Context Protocol (MCP) server that transforms your email inbox into a searchable, programmable knowledge base for Claude and other AI assistants.

## 🚀 Overview

The IMAP MCP server enables AI assistants to act as intelligent email secretaries. Unlike simple email clients, this server is optimized for high-density AI analysis, document processing, and advanced threading.

### The "Smart Secretary" Framework
The server includes a `setup_smart_labels` tool that scaffolds a standardized folder hierarchy for AI organization:
- `Secretary/Priority`: Immediate attention required.
- `Secretary/Action-Required`: Tasks identified that need your input.
- `Secretary/Processed`: Emails the AI has already handled or summarized.
- `Secretary/Calendar`: Meeting invites and schedule-related items.
- `Secretary/Newsletter`: Low-priority informational content.
- `Secretary/Waiting`: Emails pending a response from others.

### Key Capabilities
- **AI-Optimized Triage**: Fetch bulk unseen emails with critical context (To/CC/BCC) and truncated bodies (700 chars) for fast, token-efficient analysis.
- **Document Intelligence**: Deep-dive into attachments. Extract text from **PDF**, **DOCX**, and log files directly into the AI's context.
- **Gmail Power-User**: Native support for Gmail Labels and Thread IDs.
- **Advanced Search**: Natural-language friendly multi-criteria search (combine sender, subject, date ranges, and body text).
- **Streamable HTTP**: Modern deployment architecture using streamable HTTP for high-performance interaction.

## 🛠️ Deployment (Recommended)

The easiest way to run the IMAP MCP server is via Docker Compose.

### Docker Compose
Create a `docker-compose.yaml` file:

```yaml
services:
  imap-mcp:
    image: ghcr.io/non-dirty/imap-mcp:latest
    ports:
      - "8000:8000"
    environment:
      - IMAP_HOST=imap.gmail.com
      - IMAP_PORT=993
      - IMAP_USER=your-email@gmail.com
      - IMAP_PASS=your-app-password
      - IMAP_MCP_TOKEN=your-secure-shared-secret
      - IMAP_USE_SSL=true
    restart: always
```

### Environment Variables

| Variable | Description |
| :--- | :--- |
| `IMAP_HOST` | IMAP server address (e.g., `imap.gmail.com`) |
| `IMAP_USER` | Your email address |
| `IMAP_PASS` | Your password or App Password (recommended) |
| `IMAP_MCP_TOKEN` | Bearer token for securing the server connection |
| `ALLOWED_FOLDERS` | Comma-separated list of folders (e.g., `INBOX,Sent`) |

## 🤖 AI Usage Examples

Once connected, you can ask your AI assistant to perform complex workflows using natural language:

- **Triage**: "Scan my last 20 unread emails. Summarize the urgent ones and let me know if I need to reply to any project updates."
- **Document Analysis**: "Find the invoice PDF sent by 'Accounting' last week, read it, and create a task for the total amount."
- **Organization**: "Find all emails from 'Newsletter' and move them to my 'Later' label in Gmail."
- **Research**: "Search for all conversations about 'Budget 2024' between me and Sarah from last month."

## 🧰 Available Tools

| Tool | Focus | Description |
| :--- | :--- | :--- |
| **`get_unread_messages`** | **Analysis** | Fetches recent unread emails with snippet and basic headers. |
| **`search_emails`** | **Discovery** | Search using string, list, or advanced dict (e.g., `{"from": "boss@co.com", "unread": true, "since": "2024-01-01"}`). |
| **`get_email_details`** | **Discovery** | Fetches full email content, headers, and attachment metadata. |
| **`get_attachment_content`**| **Discovery** | Extracts text from PDF, DOCX, TXT, and LOG attachments. |
| **`get_email_thread`** | **Discovery** | Fetches all emails in a conversation (using Thread-ID or headers). |
| **`setup_smart_labels`** | **Organization** | Creates the `Secretary/` folder hierarchy. |
| **`modify_gmail_labels`** | **Gmail** | Native support for adding/removing Gmail labels. |
| **`process_meeting_invite`**| **Workflow** | Automatically identifies invites, checks calendar availability, and drafts an appropriate reply. |
| **`create_draft_reply`** | **Action** | Creates a MIME-formatted draft reply with proper threading. |
| **`process_email`** | **Action** | High-level tool to move, read, flag, or delete emails. |
| **`move_email`** | **Action** | Moves an email from one folder to another. |
| **`mark_as_read`** | **Action** | Marks an email as read. |
| **`mark_as_unread`** | **Action** | Marks an email as unread. |
| **`flag_email`** | **Action** | Flags (stars) an email. |
| **`delete_email`** | **Action** | Deletes an email from the server. |
| **`create_task`** | **Workflow** | Creates a local task (in `tasks.md`) from email content. |
| **`list_folders`** | **Discovery** | Lists available IMAP folders. |
| **`server_status`** | **System** | Retrieves current server status and configuration info. |

## 🔒 Security

- **App Passwords**: We strongly recommend using App-Specific Passwords rather than your primary password.
- **Bearer Tokens**: Secure your MCP connection using the `IMAP_MCP_TOKEN`.
- **Read-Only Mode**: Many analysis tools use IMAP `PEEK` to ensure emails aren't accidentally marked as read by the AI.

---
Built with the [Model Context Protocol](https://modelcontextprotocol.io/)
