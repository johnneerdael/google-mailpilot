# Docker Setup Guide

This project includes a Docker configuration to run the IMAP MCP server as a persistent service.

## Prerequisites
- Docker and Docker Compose installed on your system.

## Configuration
1. **Config File**: Ensure `config.yaml` is present in the project root. The Docker container expects it to be mounted at `/app/config/config.yaml`.
   - If you don't have one, copy the sample: `cp config.sample.yaml config.yaml` and edit it.

2. **Environment Variables** (Optional): You can override configuration using environment variables in a `.env` file or directly in `docker-compose.yml`.
   - `IMAP_MCP_TOKEN`: Set a fixed authentication token for HTTP connections. If not set, one will be generated on startup.

## Running the Service

### Start
To build and start the service in the background:
```bash
docker-compose up -d --build
```
The service will restart automatically if it crashes or if the system reboots (`restart: always`).

### Stop
To stop the service:
```bash
docker-compose down
```

### View Logs
To check the server output:
```bash
docker-compose logs -f
```

## Persistence
- **Config**: The `./config.yaml` file is mounted into the container. Changes on your host machine will be reflected in the container (restart required for config reload).
- **Tasks**: The `./tasks.json` file is mounted to persist tasks created by the agent.

## Authentication & Security

When connecting via HTTP (port 8000), authentication is **mandatory**.

*   **Auto-generated Token**: If you don't provide a token, the server generates a secure one on startup. View it with:
    ```bash
    docker-compose logs | grep "token"
    ```
*   **Fixed Token**: To set a stable token (recommended for permanent config), set the `IMAP_MCP_TOKEN` environment variable in your `docker-compose.yml`:
    ```yaml
    environment:
      - IMAP_MCP_TOKEN=my-secret-token-123
    ```

## Monitoring

*   **Health Check**: A health check endpoint is available at `http://localhost:8000/health`. It returns `{"status": "healthy", "service": "workspace-secretary"}` if the server is running. This does not require authentication.

## Connection

The server runs inside the container and exposes a Streamable HTTP endpoint for MCP clients.

*   **HTTP/SSE URL**: `http://localhost:8000/mcp` (Streamable HTTP) or `http://localhost:8000/sse` (Legacy)

Ensure port `8000` is mapped in your `docker-compose.yml` (default).

**Note for Claude Desktop / Clients**:
Standard MCP servers communicate via Stdio, but modern clients also support remote connections via HTTP/SSE.

### Option 1: Remote Connection (Recommended)
Configure your client to connect to `http://localhost:8000/mcp`. This requires the container to be running (`docker-compose up`).

### Option 2: Docker Exec (Stdio)
To use a Dockerized MCP server with a local client (like Claude Desktop) via Stdio, the client needs to invoke the `docker run` command directly.

Example Claude Desktop config:
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
        "${PWD}/config.yaml:/app/config/config.yaml",
        "-v",
        "${PWD}/tasks.json:/app/tasks.json",
        "workspace-secretary"
      ]
    }
  }
}
```
If using this method, ensure you build the image first: `docker build -t workspace-secretary .`
