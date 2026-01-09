"""Main server implementation for IMAP MCP."""

import argparse
import logging
import os
from contextlib import asynccontextmanager
import secrets
import time
import threading
from typing import AsyncIterator, Dict, Optional

from starlette.responses import JSONResponse
from starlette.requests import Request
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from workspace_secretary.config import ServerConfig, load_config, OAuthMode
from workspace_secretary.imap_client import ImapClient
from workspace_secretary.calendar_client import CalendarClient
from workspace_secretary.gmail_client import GmailClient
from workspace_secretary.smtp_client import SMTPClient
from workspace_secretary.cache import EmailCache
from workspace_secretary.resources import register_resources
from workspace_secretary.tools import register_tools
from workspace_secretary.mcp_protocol import extend_server
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("workspace_secretary")


class ClientManager:
    def __init__(self):
        self.config: Optional[ServerConfig] = None
        self.imap_client: Optional[ImapClient] = None
        self.calendar_client: Optional[CalendarClient] = None
        self.gmail_client: Optional[GmailClient] = None
        self.smtp_client: Optional[SMTPClient] = None
        self.email_cache: Optional[EmailCache] = None
        self._initialized = False
        self._sync_thread: Optional[threading.Thread] = None

    def initialize(self, config_path: Optional[str] = None) -> None:
        if self._initialized:
            return

        logger.info("Initializing client manager...")
        self.config = load_config(config_path)

        if not isinstance(self.config, ServerConfig):
            raise TypeError("Invalid server configuration")

        self.imap_client = ImapClient(self.config.imap, self.config.allowed_folders)
        self.calendar_client = CalendarClient(self.config)
        self.email_cache = EmailCache()

        logger.info(
            f"Starting server in {self.config.oauth_mode.value.upper()} mode..."
        )
        logger.info("Connecting to IMAP server...")
        self.imap_client.connect()

        if self.config.calendar and self.config.calendar.enabled:
            logger.info("Connecting to Google Calendar...")
            self.calendar_client.connect()

        if self.config.oauth_mode == OAuthMode.API:
            if self.config.imap.is_gmail and self.config.imap.oauth2:
                logger.info("Connecting to Gmail REST API...")
                self.gmail_client = GmailClient(self.config)
                self.gmail_client.connect()
        else:
            logger.info("IMAP mode: Gmail REST API disabled, using SMTP for sending")
            self.smtp_client = SMTPClient(self.config)

        self._initialized = True
        logger.info("Client manager initialized successfully")

        self._start_background_sync()

    def _start_background_sync(self) -> None:
        def sync_loop():
            logger.info("Background sync thread started")
            try:
                self._run_sync()
                while True:
                    time.sleep(300)
                    logger.info("Running incremental email cache sync...")
                    self._run_sync()
                    logger.info("Incremental cache sync completed")
            except Exception as e:
                logger.error(f"Background sync error: {e}", exc_info=True)

        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()

    def _run_sync(self) -> None:
        if not self.email_cache or not self.imap_client:
            logger.error("Cannot sync: cache or IMAP client not initialized")
            return

        def progress_callback(current: int, total: int) -> None:
            if current % 10 == 0:
                logger.info(f"Cache sync progress: {current}/{total} emails")

        self.email_cache.sync_folder(self.imap_client, "INBOX", progress_callback)

    def shutdown(self) -> None:
        if self.imap_client:
            logger.info("Disconnecting from IMAP server...")
            self.imap_client.disconnect()


_client_manager = ClientManager()


class StaticTokenVerifier:
    """Simple token verifier for static bearer token."""

    def __init__(self, token: str):
        self.token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify the bearer token."""
        if secrets.compare_digest(token, self.token):
            return AccessToken(
                token=token,
                client_id="static-client",
                scopes=[],
                expires_at=int(time.time())
                + 3600,  # Valid for 1 hour window (refreshed per request)
            )
        return None


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict]:
    yield {
        "imap_client": _client_manager.imap_client,
        "calendar_client": _client_manager.calendar_client,
        "gmail_client": _client_manager.gmail_client,
        "smtp_client": _client_manager.smtp_client,
        "oauth_mode": _client_manager.config.oauth_mode
        if _client_manager.config
        else OAuthMode.IMAP,
        "config": _client_manager.config,
        "email_cache": _client_manager.email_cache,
    }


def create_server(
    config_path: Optional[str] = None,
    debug: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    if debug:
        logger.setLevel(logging.DEBUG)

    _client_manager.initialize(config_path)
    config = _client_manager.config

    if not config:
        raise RuntimeError("Failed to load configuration")

    auth_settings = None
    token_verifier = None

    if config.bearer_auth.enabled:
        auth_token = config.bearer_auth.token or os.environ.get("IMAP_MCP_TOKEN")
        if not auth_token:
            auth_token = secrets.token_urlsafe(32)
        logger.info(f"Bearer authentication enabled. Token: {auth_token}")

        token_verifier = StaticTokenVerifier(auth_token)
        auth_settings = AuthSettings(
            issuer_url="http://localhost/",  # type: ignore
            resource_server_url="http://localhost/",  # type: ignore
            required_scopes=[],
        )

    server = FastMCP(
        "IMAP",
        instructions="IMAP Model Context Protocol server for email processing",
        lifespan=server_lifespan,
        host=host,
        port=port,
        auth=auth_settings,
        token_verifier=token_verifier,
    )

    # Store config for access in the lifespan
    setattr(server, "_config", config)

    # Create IMAP client for setup (will be recreated in lifespan)
    imap_client = ImapClient(config.imap, config.allowed_folders)

    # Register resources and tools
    register_resources(server, imap_client)
    register_tools(server, imap_client, config.oauth_mode)

    # Add server status tool
    @server.tool()
    def server_status() -> str:
        """Get server status and configuration info."""
        status = {
            "server": "IMAP MCP",
            "version": "0.1.0",
            "imap_host": config.imap.host,
            "imap_port": config.imap.port,
            "imap_user": config.imap.username,
            "imap_ssl": config.imap.use_ssl,
            "calendar_enabled": config.calendar.enabled if config.calendar else False,
        }

        if config.allowed_folders:
            status["allowed_folders"] = list(config.allowed_folders)
        else:
            status["allowed_folders"] = "All folders allowed"

        return "\n".join(f"{k}: {v}" for k, v in status.items())

    # Apply MCP protocol extension for Claude Desktop compatibility
    server = extend_server(server)

    @server.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "workspace-secretary"})

    return server


def create_app() -> "Starlette":  # type: ignore
    """Create the Starlette app for the server.

    This factory function is intended to be used by uvicorn:
    uvicorn --factory workspace_secretary.server:create_app
    """
    config_path = os.environ.get("IMAP_MCP_CONFIG")
    debug = os.environ.get("IMAP_MCP_DEBUG", "").lower() == "true"

    server = create_server(config_path=config_path, debug=debug)
    return server.streamable_http_app()


def main() -> None:
    """Run the IMAP MCP server."""
    parser = argparse.ArgumentParser(description="IMAP MCP Server")
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=os.environ.get("IMAP_MCP_CONFIG"),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable development mode",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "http"],
        help="Transport protocol to use: stdio, sse, or http (streamable http)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to for SSE/HTTP server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to for SSE/HTTP server",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version information and exit",
    )
    args = parser.parse_args()

    if args.version:
        print("IMAP MCP Server version 0.1.0")
        return

    if args.debug:
        logger.setLevel(logging.DEBUG)

    # For stdio transport, we run directly
    if args.transport == "stdio":
        server = create_server(config_path=args.config, debug=args.debug)
        if args.dev:
            logger.info("Starting server in development mode")
        logger.info("Starting server with stdio transport...")
        server.run(transport="stdio")

    # For HTTP/SSE transport, we use uvicorn
    elif args.transport in ["sse", "http"]:
        import uvicorn

        # Legacy SSE warning
        if args.transport == "sse":
            logger.warning(
                "SSE transport is deprecated. Consider using 'http' for Streamable HTTP."
            )

        logger.info(
            "Starting server{} with uvicorn...".format(
                " in development mode" if args.dev else ""
            )
        )

        # If we are in dev mode (reload), we must use the import string
        if args.dev:
            # Set env var so the module-level create_server picks up the config
            if args.config:
                os.environ["IMAP_MCP_CONFIG"] = args.config

            uvicorn.run(
                "workspace_secretary.server:create_app",
                host=args.host,
                port=args.port,
                reload=True,
                factory=True,
            )
        else:
            # If not reloading, we can create a specific server instance with the config
            server = create_server(
                config_path=args.config,
                debug=args.debug,
                host=args.host,
                port=args.port,
            )

            # Select app based on transport
            if args.transport == "sse":
                starlette_app = server.sse_app()
            else:
                starlette_app = server.streamable_http_app()

            uvicorn.run(
                starlette_app,
                host=args.host,
                port=args.port,
            )


if __name__ == "__main__":
    main()
