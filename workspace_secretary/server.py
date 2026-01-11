"""MCP server - reads from database (read-only), mutations via Engine API."""

import argparse
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.auth import SecretAuthSettings
from workspace_secretary.config import ServerConfig, load_config
from workspace_secretary.engine.database import DatabaseInterface, create_database
from workspace_secretary.engine_client import EngineClient, get_engine_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("workspace_secretary")

STATIC_TOKEN = "your-very-secure-static-token"

async def verify_static_token(token: str) -> bool:
    return token == STATIC_TOKEN

class MCPState:
    def __init__(self):
        self.config: Optional[ServerConfig] = None
        self.database: Optional[DatabaseInterface] = None
        self.engine_client: Optional[EngineClient] = None
        self.embeddings_client = None
        self._initialized = False

    def initialize(self, config_path: Optional[str] = None) -> None:
        if self._initialized:
            return

        logger.info("Initializing MCP server...")
        self.config = load_config(config_path)

        if not isinstance(self.config, ServerConfig):
            raise TypeError("Invalid server configuration")

        if self.config.database:
            try:
                self.database = create_database(self.config.database)
                logger.info(f"Database connected: {self.config.database.backend.value}")
            except Exception as e:
                logger.warning(f"Database connection failed (will retry): {e}")
                self.database = None

        if (
            self.config.database
            and self.config.database.embeddings.enabled
            and self.database
            and self.database.supports_embeddings()
        ):
            try:
                from workspace_secretary.engine.embeddings import EmbeddingsClient

                self.embeddings_client = EmbeddingsClient(
                    endpoint=self.config.database.embeddings.endpoint,
                    api_key=self.config.database.embeddings.api_key,
                    model=self.config.database.embeddings.model,
                    dimensions=self.config.database.embeddings.dimensions,
                )
                logger.info("Embeddings client initialized for semantic search")
            except Exception as e:
                logger.warning(f"Embeddings client failed: {e}")

        self.engine_client = get_engine_client()
        self._initialized = True
        logger.info("MCP server initialized")

    def get_engine_status(self) -> dict:
        if not self.engine_client:
            return {"status": "no_client"}
        try:
            return self.engine_client.get_status()
        except ConnectionError:
            return {"status": "disconnected"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


_state = MCPState()


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict]:
    yield {
        "config": _state.config,
        "database": _state.database,
        "engine_client": _state.engine_client,
        "embeddings_client": _state.embeddings_client,
    }


def create_server(
    config_path: Optional[str] = None,
    debug: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    if debug:
        logger.setLevel(logging.DEBUG)

    _state.initialize(config_path)
    config = _state.config

    if not config:
        raise RuntimeError("Failed to load configuration")

    token_verifier = None
    if config.bearer_auth.enabled and config.bearer_auth.token:
        from mcp.server.auth.provider import AccessToken, TokenVerifier

        expected_token = config.bearer_auth.token

        class SimpleTokenVerifier(TokenVerifier):
            async def verify_token(self, token: str) -> AccessToken | None:
                if token == expected_token:
                    return AccessToken(
                        token=token,
                        client_id="secretary-client",
                        scopes=[],
                    )
                return None

        token_verifier = SimpleTokenVerifier()
        logger.info("Bearer authentication enabled")

    server = FastMCP(
        "Secretary",
        instructions="Gmail Secretary - Email and Calendar MCP",
        lifespan=server_lifespan,
        host=host,
        port=port,
        token_verifier=token_verifier,
    )

    _register_tools(server, config)

    return server


def _register_tools(server: FastMCP, config: ServerConfig) -> None:
    @server.tool()
    def server_status() -> str:
        engine_status = _state.get_engine_status()
        has_db = _state.database is not None
        has_embeddings = False
        db = _state.database
        if db is not None and db.supports_embeddings():
            has_embeddings = _state.embeddings_client is not None

        lines = [
            "server: Workspace Secretary MCP",
            "version: 0.1.0",
            f"database: {'connected' if has_db else 'not_available'}",
            f"engine: {engine_status.get('status', 'unknown')}",
            f"enrolled: {engine_status.get('enrolled', False)}",
            f"semantic_search: {'available' if has_embeddings else 'not_available'}",
        ]

        if not engine_status.get("enrolled", False):
            lines.append("setup: Run 'auth_setup' to add a Google account")

        return "\n".join(lines)

    @server.tool()
    def search_emails(
        folder: str = "INBOX",
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> str:
        if not _state.database:
            return "Database not available. Engine may still be syncing."

        try:
            emails = _state.database.search_emails(
                folder=folder,
                from_addr=from_addr,
                to_addr=to_addr,
                subject_contains=subject,
                body_contains=body,
                is_unread=True if unread_only else None,
                limit=limit,
            )

            if not emails:
                return "No emails found."

            lines = [f"Found {len(emails)} emails:\n"]
            for e in emails:
                lines.extend(
                    [
                        f"UID: {e.get('uid')}",
                        f"From: {e.get('from_addr')}",
                        f"Subject: {e.get('subject')}",
                        f"Date: {e.get('date')}",
                        f"Unread: {e.get('is_unread', False)}",
                        "---",
                    ]
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    @server.tool()
    def get_email(uid: int, folder: str = "INBOX") -> str:
        if not _state.database:
            return "Database not available."

        try:
            email = _state.database.get_email_by_uid(uid, folder)
            if not email:
                return f"Email {uid} not found in {folder}."

            return "\n".join(
                [
                    f"UID: {email.get('uid')}",
                    f"Message-ID: {email.get('message_id', 'N/A')}",
                    f"From: {email.get('from_addr')}",
                    f"To: {email.get('to_addr')}",
                    f"CC: {email.get('cc_addr', '')}",
                    f"Subject: {email.get('subject')}",
                    f"Date: {email.get('date')}",
                    f"Unread: {email.get('is_unread', False)}",
                    "",
                    "Body:",
                    email.get("body_text") or email.get("body_html") or "(no content)",
                ]
            )
        except Exception as e:
            return f"Error: {e}"

    @server.tool()
    def get_unread_emails(folder: str = "INBOX", limit: int = 50) -> str:
        if not _state.database:
            return "Database not available."

        try:
            emails = _state.database.search_emails(
                folder=folder, is_unread=True, limit=limit
            )

            if not emails:
                return "No unread emails."

            lines = [f"Found {len(emails)} unread emails:\n"]
            for e in emails:
                lines.extend(
                    [
                        f"UID: {e.get('uid')}",
                        f"From: {e.get('from_addr')}",
                        f"Subject: {e.get('subject')}",
                        f"Date: {e.get('date')}",
                        "---",
                    ]
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    @server.tool()
    def get_folder_stats(folder: str = "INBOX") -> str:
        if not _state.database:
            return "Database not available."

        try:
            state = _state.database.get_folder_state(folder)
            if not state:
                return f"No data for folder {folder}."

            return "\n".join(
                [
                    f"Folder: {folder}",
                    f"Total: {state.get('total_count', 0)}",
                    f"Unread: {state.get('unread_count', 0)}",
                    f"Last sync: {state.get('last_sync', 'Never')}",
                ]
            )
        except Exception as e:
            return f"Error: {e}"

    _db = _state.database
    _emb = _state.embeddings_client
    if _db is not None and _db.supports_embeddings() and _emb is not None:

        @server.tool()
        async def semantic_search(
            query: str, folder: str = "INBOX", limit: int = 20
        ) -> str:
            """Search emails by meaning using AI embeddings."""
            db = _state.database
            emb = _state.embeddings_client
            if db is None or emb is None:
                return "Semantic search not available."
            result = await emb.embed_query(query)
            try:
                emails = db.semantic_search(
                    query_embedding=result.embedding,
                    folder=folder,
                    limit=limit,
                )

                if not emails:
                    return "No semantically similar emails found."

                lines = [f"Found {len(emails)} relevant emails:\n"]
                for e in emails:
                    similarity = e.get("similarity", 0)
                    lines.extend(
                        [
                            f"UID: {e.get('uid')} (similarity: {similarity:.2f})",
                            f"From: {e.get('from_addr')}",
                            f"Subject: {e.get('subject')}",
                            f"Date: {e.get('date')}",
                            "---",
                        ]
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Semantic search error: {e}"

        @server.tool()
        def find_similar_emails(
            uid: int, folder: str = "INBOX", limit: int = 10
        ) -> str:
            """Find emails similar to a specific email."""
            db = _state.database
            if db is None:
                return "Database not available."
            try:
                emails = db.find_similar_emails(uid, folder, limit)

                if not emails:
                    return f"No similar emails found for UID {uid}."

                lines = [f"Found {len(emails)} similar emails:\n"]
                for e in emails:
                    similarity = e.get("similarity", 0)
                    lines.extend(
                        [
                            f"UID: {e.get('uid')} (similarity: {similarity:.2f})",
                            f"From: {e.get('from_addr')}",
                            f"Subject: {e.get('subject')}",
                            "---",
                        ]
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Error: {e}"

    @server.tool()
    def mark_as_read(uid: int, folder: str = "INBOX") -> str:
        if not _state.engine_client:
            return "Engine not available."

        try:
            result = _state.engine_client.mark_read(uid, folder)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return f"Email {uid} marked as read."
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running. Start the engine first."

    @server.tool()
    def mark_as_unread(uid: int, folder: str = "INBOX") -> str:
        if not _state.engine_client:
            return "Engine not available."

        try:
            result = _state.engine_client.mark_unread(uid, folder)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return f"Email {uid} marked as unread."
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."

    @server.tool()
    def move_email(uid: int, folder: str, destination: str) -> str:
        if not _state.engine_client:
            return "Engine not available."

        try:
            result = _state.engine_client.move_email(uid, folder, destination)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return f"Email {uid} moved to {destination}."
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."

    @server.tool()
    def modify_labels(uid: int, folder: str, labels: str, action: str = "add") -> str:
        if not _state.engine_client:
            return "Engine not available."

        label_list = [l.strip() for l in labels.split(",")]

        try:
            result = _state.engine_client.modify_labels(uid, folder, label_list, action)
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return f"Labels {action}: {labels}"
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."

    @server.tool()
    def trigger_sync() -> str:
        if not _state.engine_client:
            return "Engine not available."

        try:
            result = _state.engine_client.trigger_sync()
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return "Sync triggered."
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."

    @server.tool()
    def create_calendar_event(
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary",
        meeting_type: Optional[str] = None,
    ) -> str:
        if not _state.engine_client:
            return "Engine not available."

        try:
            result = _state.engine_client.create_calendar_event(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                calendar_id=calendar_id,
                meeting_type=meeting_type,
            )
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                event = result.get("event", {})
                return f"Event created: {event.get('htmlLink', 'Success')}"
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."

    @server.tool()
    def respond_to_meeting(event_id: str, calendar_id: str, response: str) -> str:
        if not _state.engine_client:
            return "Engine not available."

        if response not in ["accepted", "declined", "tentative"]:
            return f"Invalid response: {response}. Use: accepted, declined, tentative"

        try:
            result = _state.engine_client.respond_to_meeting(
                event_id, calendar_id, response
            )
            if result.get("status") == "no_account":
                return result.get("message", "No account configured")
            if result.get("status") == "ok":
                return f"Response '{response}' sent."
            return f"Error: {result.get('message', 'Unknown error')}"
        except ConnectionError:
            return "Engine not running."


def main() -> None:
    parser = argparse.ArgumentParser(description="Workspace Secretary MCP Server")
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=os.environ.get("CONFIG_PATH"),
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "http"],
        help="Transport protocol",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    server = create_server(config_path=args.config, debug=args.debug)

    if args.transport == "stdio":
        logger.info("Starting MCP server (stdio)...")
        server.run(transport="stdio")
    else:
        import uvicorn

        logger.info(f"Starting MCP server ({args.transport})...")
        if args.transport == "sse":
            app = server.sse_app()
        else:
            app = server.streamable_http_app()

        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
