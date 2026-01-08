# Client Setup Guide

This guide explains how to configure popular MCP clients to communicate with the Dockerized IMAP server.

## Connection Methods

There are two primary ways to connect your MCP client to the Docker container.

### Method 1: Connect to Persistent Service (Recommended)

This method connects to the container already running via `docker-compose`.

*   **Prerequisite**: You must have the service running (`docker-compose up -d`).
*   **Why use this?**
    *   **Shared State**: It shares the authentication state and configuration of the running service.
    *   **Performance**: Startup is instant because the container is already running; we just execute a command inside it.
    *   **Resources**: Reuses the existing container's memory and CPU.

**Command Structure:**
```bash
docker exec -i workspace-secretary uv run python -m workspace_secretary.server
```

### Method 2: Ephemeral Container

This method spins up a new, temporary container for every session.

*   **Why use this?**
    *   **Isolation**: Totally separate process from your main background service.
    *   **No Dependency**: Does not require `docker-compose` to be running.
*   **Drawback**: Slower startup and requires careful volume mounting to share config/auth.

**Command Structure:**
```bash
docker run -i --rm \
  -v /path/to/your/config.yaml:/app/config/config.yaml \
  ghcr.io/jneerdaekl/workspace-secretary:latest
```

### Method 3: Streamable HTTP Connection (Recommended for Remote/Docker)

This method connects to the server running inside Docker via Streamable HTTP (replaces legacy SSE).

*   **Prerequisite**: You must have the service running (`docker-compose up -d`) and port 8000 exposed.
*   **Authentication**: Requires a Bearer Token (see "Finding the Token" below).
*   **Why use this?**
    *   **Simplicity**: No complex Docker commands in your client config.
    *   **Compatibility**: Works well with clients that support remote MCP servers.
    *   **Network**: Allows connecting to a server running on a different machine.
    *   **Performance**: Better performance and standard web infrastructure integration.

**URL:** `http://localhost:8000/mcp`

### Finding the Token

The server generates a secure token on startup if one isn't provided. You can find it in the logs:

```bash
docker-compose logs | grep "token"
# Output: No IMAP_MCP_TOKEN found in environment. Generated temporary token: <YOUR_TOKEN>
```

To set a fixed token, add `IMAP_MCP_TOKEN=your-secret-token` to your `docker-compose.yml` environment variables.

---

## 1. Claude Desktop (and OpenCode)

Most desktop MCP clients use a configuration file located in your user directory.

**Config Location:**
*   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
*   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

For **OpenCode** or compatible tools, check their specific config documentation (often `~/.config/opencode/mcp.json` or similar).

### Configuration (Method 3 - Streamable HTTP)

Add this to your `mcpServers` block. Note that you must include the `headers` field with your authentication token.

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

### Configuration (Method 1 - Persistent Docker Exec)

Add this to your `mcpServers` block:

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

### Configuration (Method 2 - Ephemeral)

**Note:** You must replace `/absolute/path/to/config.yaml` with the actual path on your host machine.

```json
{
  "mcpServers": {
    "workspace-secretary": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "/absolute/path/to/config.yaml:/app/config/config.yaml",
        "ghcr.io/jneerdaekl/workspace-secretary:latest"
      ]
    }
  }
}
```

---

## 2. Roo Code / Cline (VS Code Extensions)

These VS Code extensions act as autonomous coding agents. They can read from the standard Claude Desktop config file (Method 1 above), but you can also configure them directly in their settings.

### UI Configuration

1.  Open the Extension Settings (gear icon in the extension panel).
2.  Look for "MCP Servers" or "Edit MCP Settings".
3.  Enter the following details:

**For Persistent Service (Method 1):**

*   **Name**: `workspace-secretary`
*   **Command**: `docker`
*   **Args**:
    *   `exec`
    *   `-i`
    *   `workspace-secretary`
    *   `uv`
    *   `run`
    *   `python`
    *   `-m`
    *   `workspace_secretary.server`

**For Ephemeral Container (Method 2):**

*   **Name**: `workspace-secretary`
*   **Command**: `docker`
*   **Args**:
    *   `run`
    *   `-i`
    *   `--rm`
    *   `-v`
    *   `/absolute/path/to/config.yaml:/app/config/config.yaml`
    *   `ghcr.io/jneerdaekl/workspace-secretary:latest`

**For Streamable HTTP Connection (Method 3):**

If your version supports adding a URL-based server in the UI, use:
*   **URL**: `http://localhost:8000/mcp`
*   **Headers**: Add a header `Authorization` with value `Bearer <YOUR_TOKEN>` (if supported by UI).

Otherwise, use the "Edit MCP Settings" button to open the configuration file and add:

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

---

## 3. Kilo Code

Kilo Code is another compatible environment. Configuration is generally similar to VS Code-based tools.

If modifying a JSON configuration file:

### Persistent Service (Method 1)

```json
"workspace-secretary": {
  "command": "docker",
  "args": [
    "exec", "-i", "workspace-secretary", 
    "uv", "run", "python", "-m", "workspace_secretary.server"
  ]
}
```

### Streamable HTTP Connection (Method 3)

```json
"workspace-secretary": {
  "url": "http://localhost:8000/mcp",
  "headers": {
    "Authorization": "Bearer <YOUR_TOKEN>"
  }
}
```
