# Client Setup Guide

This guide explains how to configure popular MCP clients to communicate with the Dockerized Google MailPilot server.

## Connection Methods

There are two primary ways to connect your MCP client to the Docker container.

### Method 1: Streamable HTTP Connection (Recommended)

This method connects to the server running inside Docker via Streamable HTTP. This is the most modern and performant way to connect.

*   **Prerequisite**: You must have the service running (`docker-compose up -d`) and port 8000 exposed.
*   **Authentication**: Requires a Bearer Token (see "Finding the Token" below).
*   **Why use this?**
    *   **Simplicity**: No complex Docker commands in your client config.
    *   **Network**: Allows connecting to a server running on a different machine.
    *   **Performance**: Better performance and standard web infrastructure integration.

**URL:** `http://localhost:8000/mcp`

### Method 2: Connect to Persistent Service (Legacy/Stdio)

This method connects to the container already running via `docker-compose` by executing a command inside it.

*   **Prerequisite**: You must have the service running (`docker-compose up -d`).
*   **Command Structure:** `docker exec -i workspace-secretary uv run python -m workspace_secretary.server`

## Authentication

### Finding the Token

The server generates a secure token on startup if one isn't provided. You can find it in the logs:

```bash
docker-compose logs | grep "token"
# Output: No IMAP_MCP_TOKEN found in environment. Generated temporary token: <YOUR_TOKEN>
```

To set a fixed token, add `IMAP_MCP_TOKEN=your-secret-token` to your `docker-compose.yml` environment variables.

## Client Configurations

### 1. Claude Desktop & OpenCode

**Config Location:**
*   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
*   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**Configuration (Streamable HTTP):**

Add this to your `mcpServers` block. **Important:** You must include the `headers` field with your authentication token.

```json
{
  "mcpServers": {
    "workspace-secretary": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

### 2. Roo Code / Cline (VS Code)

1.  Open Extension Settings.
2.  Look for "MCP Servers" configuration.
3.  Add a new server with:
    *   **URL**: `http://localhost:8000/mcp`
    *   **Headers**: `{"Authorization": "Bearer <YOUR_TOKEN>"}`

### 3. Docker Exec Fallback (Not Recommended)

If you must use Stdio communication with a running container:

```json
{
  "mcpServers": {
    "workspace-secretary": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "workspace-secretary",
        "uv",
        "run",
        "python",
        "-m",
        "workspace_secretary.server"
      ]
    }
  }
}
```
