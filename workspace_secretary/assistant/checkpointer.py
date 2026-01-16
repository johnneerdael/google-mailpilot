"""PostgreSQL checkpointer for LangGraph conversation persistence."""

import logging
from contextlib import ExitStack
from typing import Optional

from langgraph.checkpoint.postgres import PostgresSaver

from workspace_secretary.config import PostgresConfig

logger = logging.getLogger(__name__)

_checkpointer: Optional[PostgresSaver] = None
_exit_stack: Optional[ExitStack] = None


def create_checkpointer(postgres_config: PostgresConfig) -> PostgresSaver:
    """Create and initialize a PostgreSQL checkpointer.

    Args:
        postgres_config: PostgreSQL connection configuration

    Returns:
        Configured PostgresSaver instance
    """
    global _checkpointer, _exit_stack

    if _checkpointer is not None:
        return _checkpointer

    # Build connection string
    conn_string = postgres_config.connection_string

    # Create exit stack to manage context manager lifecycle
    _exit_stack = ExitStack()

    # from_conn_string returns a context manager, enter it and keep it alive
    _checkpointer = _exit_stack.enter_context(
        PostgresSaver.from_conn_string(conn_string)
    )

    # Initialize schema (creates tables if not exist)
    _checkpointer.setup()

    logger.info("PostgreSQL checkpointer initialized")
    return _checkpointer


def get_checkpointer() -> Optional[PostgresSaver]:
    """Get the global checkpointer instance.

    Returns:
        The checkpointer if initialized, None otherwise
    """
    return _checkpointer


def close_checkpointer() -> None:
    """Close the checkpointer connection."""
    global _checkpointer, _exit_stack
    if _exit_stack is not None:
        _exit_stack.close()
        _exit_stack = None
    _checkpointer = None
    logger.info("PostgreSQL checkpointer closed")
