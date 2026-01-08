# Google Workspace Secretary MCP

Google Workspace Secretary MCP is a Model Context Protocol (MCP) server that provides tools for interacting with Google Workspace (Gmail and Calendar) as well as any IMAP/SMTP compatible email service.

## Core Identity
This tool is designed to act as an AI-powered secretary. It doesn't just read emails; it understands them, manages your calendar, and helps you respond intelligently.

## Docker Usage (Primary Method)

The easiest way to run Google Workspace Secretary MCP is via Docker.

### Prerequisites
- Docker and Docker Compose installed.
- Google Cloud Project with Gmail and Calendar APIs enabled (if using Google Workspace).
- `credentials.json` from your Google Cloud Project.

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/johnneerdael/Google-Workspace-Secretary-MCP.git
   cd Google-Workspace-Secretary-MCP
   ```

2. **Configure:**
   Copy `config.sample.yaml` to `config.yaml` and fill in your details.
   ```bash
   cp config.sample.yaml config.yaml
   ```

3. **Run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

4. **Authentication:**
   If using OAuth2, you need to authorize the application:
   ```bash
   docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup --config /app/config/config.yaml
   ```

## Agent and Subagent Workflows

Google Workspace Secretary MCP is built to support advanced agentic workflows.

### Task Handling
The server provides atomic tools that can be composed by an LLM to handle complex tasks:
- `list_unread_emails`: Discover new work.
- `get_email_details`: Understand context.
- `check_calendar`: Verify availability.
- `draft_reply` / `send_email`: Take action.

### Subagents
You can deploy specialized "subagents" using this MCP server:
- **Triage Agent:** Periodically checks for new emails and categorizes them.
- **Scheduling Agent:** Specifically handles meeting invites, checking calendar availability and drafting responses.
- **Knowledge Agent:** Searches past emails to answer questions or provide context for new tasks.

## GitHub Repository
[https://github.com/johnneerdael/Google-Workspace-Secretary-MCP](https://github.com/johnneerdael/Google-Workspace-Secretary-MCP)
