# OAuth2 Authentication with Docker (IMAP Service)

*Note: This guide explains how to authenticate the IMAP Service with your Email Provider (e.g., Gmail). This is different from the Bearer Token authentication used to connect your MCP Client to the Docker container.*

When running the IMAP MCP server in Docker, the OAuth2 authentication flow requires a slightly different approach because the redirect callback happens on `localhost` (which, inside the container, is different from your host machine's `localhost`).

## Prerequisites

- Ensure your `docker-compose.yml` exposes port 8080 (already configured in the default setup).
- Ensure you have your `config.yaml` file prepared (you can start by copying `config.sample.yaml`).

**Note on Credentials:**
The `config.sample.yaml` file includes the public Client ID and Secret for Mozilla Thunderbird. Using these credentials can simplify setup as they are already verified by Google/Gmail, often avoiding the need to create your own GCP project credentials.

## Authentication Steps

1.  **Start the Container**
    Start the Docker container in the background (or foreground if you prefer logs):
    ```bash
    docker-compose up -d
    ```

2.  **Initiate Authentication**
    You need to run the authentication command *inside* the running container.

    ```bash
    docker exec -it workspace-secretary uv run python -m workspace_secretary.auth_setup --config /app/config/config.yaml
    ```
    *(Note: We use the path `/app/config/config.yaml` because that is where the volume is mounted inside the container).*

3.  **Complete the Flow in Browser**
    - The command will print a URL to your terminal.
    - Copy and paste this URL into your browser on your host machine.
    - Log in to your email provider (e.g., Gmail) and grant the requested permissions.

4.  **Redirect and Token Capture**
    - After you approve access, the browser will redirect you to `http://localhost:8080/...`.
    - Because we mapped port `8080` of the container to port `8080` of your host, this request will reach the container.
    - The script inside the container will capture the authorization code, exchange it for a refresh token, and save it to your `config.yaml` (which is mounted from your host system).

5.  **Restart (If Necessary)**
    If the main application requires the token to start and was failing before, restart the container:
    ```bash
    docker-compose restart
    ```

## Troubleshooting

- **Connection Refused on Redirect:** If the redirect to `localhost:8080` fails, ensure nothing else on your host machine is using port 8080.
- **"App not verified" Warning:** If you are using your own custom GCP credentials (instead of the Thunderbird ones), you might see a warning screen. You can usually click "Advanced" -> "Go to (App Name) (unsafe)" to proceed for testing purposes.
