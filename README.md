# IMAP MCP Server

An AI-native Model Context Protocol (MCP) server that transforms your email inbox into a searchable, programmable knowledge base for Claude and other AI assistants.

## 🚀 Overview

The IMAP MCP server enables AI assistants to act as intelligent email secretaries. Unlike simple email clients, this server is optimized for high-density AI analysis, document processing, and advanced threading.

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

| Tool | Focus | Use Case |
| :--- | :--- | :--- |
| `get_unseen_emails` | **Analysis** | Bulk triage of newest unread messages. |
| `get_attachment_content` | **Reading** | Extract text from PDF, DOCX, TXT. |
| `advanced_search` | **Discovery** | Complex searches with multiple filters. |
| `get_gmail_thread` | **Context** | View full conversations via Gmail Thread ID. |
| `modify_gmail_labels` | **Organization**| Manage Gmail labels (add/remove/set). |
| `draft_reply_tool` | **Action** | Create draft responses. |
| `process_meeting_invite` | **Workflow** | Auto-identify invites and check availability. |

## 🔒 Security

- **App Passwords**: We strongly recommend using App-Specific Passwords rather than your primary password.
- **Bearer Tokens**: Secure your MCP connection using the `IMAP_MCP_TOKEN`.
- **Read-Only Mode**: Many analysis tools use IMAP `PEEK` to ensure emails aren't accidentally marked as read by the AI.

---
Built with the [Model Context Protocol](https://modelcontextprotocol.io/)
