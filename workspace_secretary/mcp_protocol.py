"""MCP Protocol Implementation for IMAP MCP server.

This module implements the required MCP protocol methods that are not directly
supported by FastMCP but needed for Claude desktop compatibility.
"""

import logging
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP, Context

logger = logging.getLogger(__name__)


def extend_server(server: FastMCP) -> FastMCP:
    """Extend a FastMCP server with additional MCP protocol methods.

    Args:
        server: The FastMCP server instance to extend

    Returns:
        The extended server instance
    """
    server_any: Any = server

    @server.resource("email://folders")
    def email_folders() -> str:
        """List all available email folders."""
        logger.info("Accessing email folders resource")

        if hasattr(server_any, "_lifespan_context") and server_any._lifespan_context:
            imap_client = server_any._lifespan_context.get("imap_client")
            if imap_client:
                folders = imap_client.list_folders()
                return "\n".join(folders)

        return "No email folders available"

    @server.tool()
    def email_search(query: str) -> Dict[str, Any]:
        """Search for emails using a query string.

        Args:
            query: Search query string

        Returns:
            Dict containing search results
        """
        logger.info(f"Searching emails with query: {query}")

        if hasattr(server_any, "_lifespan_context") and server_any._lifespan_context:
            imap_client = server_any._lifespan_context.get("imap_client")
            if imap_client:
                return {"results": "Search results would be returned here"}

        return {"results": "No results found"}

    @server.prompt()
    def search_emails(query: str) -> str:
        """Create prompt for searching emails.

        Args:
            query: Search query for emails

        Returns:
            Formatted prompt string
        """
        return f"Search for emails that match: {query}"

    @server.prompt()
    def compose_email(to: str, subject: str = "", body: str = "") -> str:
        """Create prompt for composing a new email.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body content

        Returns:
            Formatted prompt string
        """
        return f"Compose an email to: {to}\nSubject: {subject}\n\n{body}"

    if hasattr(server_any, "_low_level_server"):
        low_level = server_any._low_level_server

        if not hasattr(low_level, "has_method") or not low_level.has_method(
            "sampling/createMessage"
        ):
            logger.info(
                "Registering additional low-level methods for Claude desktop compatibility"
            )

    return server
