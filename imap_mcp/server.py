"""Main server implementation for IMAP MCP."""

import argparse
import logging
import os
from contextlib import asynccontextmanager
import secrets
import time
from typing import AsyncIterator, Dict, Optional

from starlette.responses import JSONResponse
from starlette.requests import Request
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from imap_mcp.config import ServerConfig, load_config
from imap_mcp.imap_client import ImapClient
from imap_mcp.calendar_client import CalendarClient
from imap_mcp.gmail_client import GmailClient
from imap_mcp.resources import register_resources
from imap_mcp.tools import register_tools
from imap_mcp.mcp_protocol import extend_server

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("imap_mcp")


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
    """Server lifespan manager to handle IMAP client lifecycle.

    Args:
        server: MCP server instance

    Yields:
        Context dictionary containing IMAP client
    """
    # Access the config that was set in create_server
    # The config is stored in the server's state
    config = getattr(server, "_config", None)
    if not config:
        # This is a fallback in case we can't find the config
        config = load_config()

    if not isinstance(config, ServerConfig):
        raise TypeError("Invalid server configuration")

    imap_client = ImapClient(config.imap, config.allowed_folders)
    calendar_client = CalendarClient(config)
    gmail_client = GmailClient(config)

    try:
        # Connect to IMAP server
        logger.info("Connecting to IMAP server...")
        imap_client.connect()

        # Connect to Calendar if enabled
        if config.calendar and config.calendar.enabled:
            logger.info("Connecting to Google Calendar...")
            calendar_client.connect()

        # Connect to Gmail API if it's Gmail
        if config.imap.is_gmail and config.imap.oauth2:
            logger.info("Connecting to Gmail REST API...")
            gmail_client.connect()

        # Yield the context with the clients
        yield {
            "imap_client": imap_client,
            "calendar_client": calendar_client,
            "gmail_client": gmail_client,
        }
    finally:
        # Disconnect from IMAP server
        logger.info("Disconnecting from IMAP server...")
        imap_client.disconnect()


def create_server(
    config_path: Optional[str] = None,
    debug: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Create and configure the MCP server.

    Args:
        config_path: Path to configuration file
        debug: Enable debug mode
        host: Host to bind to (for SSE)
        port: Port to bind to (for SSE)

    Returns:
        Configured MCP server instance
    """
    # Set up logging level
    if debug:
        logger.setLevel(logging.DEBUG)

    # Load configuration
    config = load_config(config_path)

    # Bearer Token Authentication
    # We only enable auth if it's explicitly requested via env var or always generate if HTTP transport?
    # The prompt implies we should always have it for HTTP.
    # Let's check for an existing token in env, or generate one.
    auth_token = os.environ.get("IMAP_MCP_TOKEN")
    if not auth_token:
        auth_token = secrets.token_urlsafe(32)
        logger.warning(
            f"No IMAP_MCP_TOKEN found in environment. Generated temporary token: {auth_token}"
        )
    else:
        logger.info("Using configured IMAP_MCP_TOKEN from environment.")

    # Create token verifier
    token_verifier = StaticTokenVerifier(auth_token)

    # Create AuthSettings - required if using token_verifier in FastMCP init
    # Note: FastMCP checks: if token_verifier AND NOT auth_settings -> ValueError.
    # We need dummy auth settings to satisfy the check, even if we use our own verifier.
    # The issuer_url is required by pydantic model.
    auth_settings = AuthSettings(
        issuer_url="http://localhost/",  # type: ignore
        resource_server_url="http://localhost/",  # type: ignore
        required_scopes=[],
    )

    # Create MCP server with all the necessary capabilities
    server = FastMCP(
        "IMAP",
        instructions="IMAP Model Context Protocol server for email processing",
        # description="IMAP Model Context Protocol server for email processing", # description not supported
        # version="0.1.0", # version not supported in FastMCP init
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
    register_tools(server, imap_client)

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
        return JSONResponse({"status": "healthy", "service": "imap-mcp"})

    return server


def create_app() -> "Starlette":  # type: ignore
    """Create the Starlette app for the server.

    This factory function is intended to be used by uvicorn:
    uvicorn --factory imap_mcp.server:create_app
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
                "imap_mcp.server:create_app",
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
