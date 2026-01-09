"""MCP resources implementation - reads from database."""

import json
import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP, Context

from workspace_secretary.config import ServerConfig
from workspace_secretary.engine.database import DatabaseInterface

logger = logging.getLogger(__name__)


def get_database_from_context(ctx: Context) -> Optional[DatabaseInterface]:
    ctx_any: Any = ctx
    return ctx_any.request_context.lifespan_context.get("database")


def get_config_from_context(ctx: Context) -> Optional[ServerConfig]:
    ctx_any: Any = ctx
    return ctx_any.request_context.lifespan_context.get("config")


def register_resources(mcp: FastMCP) -> None:
    """Register MCP resources for email access via database."""

    @mcp.resource("email://folders")
    async def get_folders() -> str:
        """List available email folders from database."""
        ctx_any: Any = Context
        ctx = ctx_any.get_current()
        db = get_database_from_context(ctx)

        if not db:
            return json.dumps({"error": "Database not available"})

        try:
            folders = db.get_synced_folders()
            return json.dumps(folders, indent=2)
        except Exception as e:
            logger.error(f"Error listing folders: {e}")
            return json.dumps({"error": str(e)})

    @mcp.resource("email://{folder}/list")
    async def list_emails(folder: str) -> str:
        """List emails in a folder from database."""
        ctx_any: Any = Context
        ctx = ctx_any.get_current()
        db = get_database_from_context(ctx)

        if not db:
            return json.dumps({"error": "Database not available"})

        try:
            emails = db.search_emails(folder=folder, limit=50)

            results = []
            for email in emails:
                results.append(
                    {
                        "uid": email.get("uid"),
                        "folder": folder,
                        "from": email.get("from_addr"),
                        "to": email.get("to_addr"),
                        "subject": email.get("subject"),
                        "date": str(email.get("date")) if email.get("date") else None,
                        "is_unread": email.get("is_unread", False),
                        "is_important": email.get("is_important", False),
                    }
                )

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error listing emails: {e}")
            return json.dumps({"error": str(e)})

    @mcp.resource("email://{folder}/{uid}")
    async def get_email(folder: str, uid: str) -> str:
        """Get a specific email from database."""
        ctx_any: Any = Context
        ctx = ctx_any.get_current()
        db = get_database_from_context(ctx)

        if not db:
            return "Database not available"

        try:
            email = db.get_email_by_uid(int(uid), folder)

            if not email:
                return f"Email {uid} not found in {folder}"

            parts = [
                f"From: {email.get('from_addr')}",
                f"To: {email.get('to_addr')}",
            ]

            if email.get("cc_addr"):
                parts.append(f"Cc: {email.get('cc_addr')}")

            if email.get("date"):
                parts.append(f"Date: {email.get('date')}")

            parts.append(f"Subject: {email.get('subject')}")
            parts.append(f"Unread: {email.get('is_unread', False)}")
            parts.append(f"Important: {email.get('is_important', False)}")
            parts.append("")

            body = email.get("body_text") or email.get("body_html") or "(no content)"
            parts.append(body)

            return "\n".join(parts)
        except Exception as e:
            logger.error(f"Error fetching email: {e}")
            return f"Error: {e}"

    @mcp.resource("email://search/{query}")
    async def search_emails(query: str) -> str:
        """Search emails in database."""
        ctx_any: Any = Context
        ctx = ctx_any.get_current()
        db = get_database_from_context(ctx)

        if not db:
            return json.dumps({"error": "Database not available"})

        try:
            emails = db.search_emails(
                subject_contains=query,
                body_contains=query,
                limit=50,
            )

            results = []
            for email in emails:
                results.append(
                    {
                        "uid": email.get("uid"),
                        "folder": email.get("folder"),
                        "from": email.get("from_addr"),
                        "subject": email.get("subject"),
                        "date": str(email.get("date")) if email.get("date") else None,
                        "is_unread": email.get("is_unread", False),
                    }
                )

            return json.dumps(results, indent=2)
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return json.dumps({"error": str(e)})
