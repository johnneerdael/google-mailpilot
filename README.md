# Google Workspace Secretary MCP

Google Workspace Secretary MCP is an AI-native Model Context Protocol (MCP) server that transforms your Google Workspace (Gmail, Calendar) and email inboxes into a searchable, programmable knowledge base for Claude and other AI assistants.

## 🚀 Overview

The Google Workspace Secretary MCP server enables AI assistants to act as intelligent email and calendar secretaries. Unlike simple email clients, this server is optimized for high-density AI analysis, document processing, and advanced calendar management.

### The "Smart Secretary" Framework
The server includes tools that scaffold a standardized organization hierarchy:
- **Triage**: Intelligent discovery of new work.
- **Context**: Deep understanding of email threads and documents.
- **Action**: Managing calendar invites and drafting professional replies.

### Key Capabilities
- **Google Workspace Native**: Full support for Gmail Labels, Thread IDs, and Google Calendar events.
- **AI-Optimized Triage**: Fetch bulk unseen emails with critical context (To/CC/BCC) and truncated bodies (700 chars) for fast, token-efficient analysis.
- **Document Intelligence**: Deep-dive into attachments. Extract text from **PDF**, **DOCX**, and log files directly into the AI's context.
- **Advanced Search**: Natural-language friendly multi-criteria search.
- **Calendar Orchestration**: Automatically check availability, parse invites, and draft replies.

## 🛠️ Deployment (Recommended)

The easiest way to run the Google Workspace Secretary MCP server is via Docker Compose.

### Docker Compose
Create a `docker-compose.yaml` file:

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/workspace-secretary:latest
    ports:
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config/config.yaml
      - ./credentials.json:/app/credentials.json
    restart: always
```

See [docs/DOCKER_GUIDE.md](docs/DOCKER_GUIDE.md) for detailed setup instructions.

## 🤖 AI Usage Examples

Once connected, you can ask your AI assistant to perform complex workflows using natural language:

- **Triage**: "Scan my last 20 unread emails. Summarize the urgent ones and let me know if I need to reply to any project updates."
- **Scheduling**: "I received a meeting invite from John for tomorrow at 2 PM. Check my calendar and if I'm free, draft a polite acceptance."
- **Document Analysis**: "Find the invoice PDF sent by 'Accounting' last week, read it, and create a task for the total amount."

## 🧰 Available Tools

| Tool | Focus | Description |
| :--- | :--- | :--- |
| **`get_unread_messages`** | **Analysis** | Fetches recent unread emails with snippet and basic headers. |
| **`search_emails`** | **Discovery** | Search using string, list, or advanced criteria. |
| **`get_email_details`** | **Discovery** | Fetches full email content, headers, and attachment metadata. |
| **`get_attachment_content`**| **Discovery** | Extracts text from PDF, DOCX, TXT, and LOG attachments. |
| **`check_calendar`** | **Calendar** | Lists calendar events for a specific time range. |
| **`process_meeting_invite`**| **Workflow** | Automatically identifies invites, checks calendar availability, and drafts an appropriate reply. |
| **`create_draft_reply`** | **Action** | Creates a MIME-formatted draft reply with proper threading. |
| **`send_email`** | **Action** | Sends an email via SMTP or Gmail API. |

## 🔒 Security

- **OAuth2**: Secure authentication with Google Workspace using OAuth2.
- **App Passwords**: Fallback support for IMAP/SMTP with App-Specific Passwords.
- **Bearer Tokens**: Secure your MCP connection using a secret token.

---
Built with the [Model Context Protocol](https://modelcontextprotocol.io/)
GitHub: [https://github.com/johnneerdael/Google-Workspace-Secretary-MCP](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP)
