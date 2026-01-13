"""
Web UI database access layer - read-only queries using shared PostgresDatabase.
"""

from typing import Optional
from contextlib import contextmanager
import logging
from psycopg.rows import dict_row

from workspace_secretary.db import PostgresDatabase
from workspace_secretary.db.queries import emails as email_q
from workspace_secretary.db.queries import embeddings as emb_q
from workspace_secretary.db.queries import contacts as contact_q

logger = logging.getLogger(__name__)

_db: Optional[PostgresDatabase] = None


def get_db() -> PostgresDatabase:
    """Get or create singleton PostgresDatabase instance for web UI."""
    global _db
    if _db is None:
        from workspace_secretary.config import load_config

        config = load_config()
        if not config.database or not config.database.postgres:
            logger.error("PostgreSQL configuration is missing from config.yaml")
            raise RuntimeError("PostgreSQL configuration is missing")

        db_config = config.database.postgres
        embedding_dimensions = 1536
        if hasattr(config.database, "embeddings") and config.database.embeddings:
            embedding_dimensions = getattr(
                config.database.embeddings, "dimensions", 1536
            )

        _db = PostgresDatabase(
            host=db_config.host,
            port=db_config.port,
            database=db_config.database,
            user=db_config.user,
            password=db_config.password,
            ssl_mode=getattr(db_config, "ssl_mode", "prefer"),
            embedding_dimensions=embedding_dimensions,
        )
        _db.initialize()
        logger.info("Web UI database initialized")
    return _db


def get_vector_type() -> str:
    """Get the vector type based on embedding dimensions."""
    db = get_db()
    return db._vector_type


@contextmanager
def get_conn():
    """Get database connection from shared pool."""
    db = get_db()
    with db.connection() as conn:
        yield conn


def get_pool():
    """Compatibility function - returns underlying connection pool.

    DEPRECATED: Use get_db() or get_conn() instead.
    This function exists for backward compatibility with route handlers
    that directly accessed the connection pool.
    """
    return get_db()._pool


def get_inbox_emails(
    folder: str, limit: int, offset: int, unread_only: bool = False
) -> list[dict]:
    return email_q.get_inbox_emails(get_db(), folder, limit, offset, unread_only)


def get_email(uid: int, folder: str) -> Optional[dict]:
    return email_q.get_email(get_db(), uid, folder)


def get_neighbor_uids(
    folder: str, uid: int, unread_only: bool = False
) -> dict[str, Optional[int]]:
    return email_q.get_neighbor_uids(get_db(), folder, uid, unread_only)


def get_thread(uid: int, folder: str) -> list[dict]:
    return email_q.get_thread(get_db(), uid, folder)


def search_emails(query: str, folder: str, limit: int) -> list[dict]:
    return email_q.search_emails_fts(get_db(), query, folder, limit)


def has_embeddings() -> bool:
    return emb_q.has_embeddings(get_db())


def get_folders() -> list[str]:
    return email_q.get_folders(get_db())


def search_emails_advanced(
    query: str, folder: str, limit: int, filters: dict
) -> list[dict]:
    return email_q.search_emails_advanced(get_db(), query, folder, limit, filters)


def semantic_search(
    query_embedding: list[float], folder: str, limit: int, threshold: float = 0.5
) -> list[dict]:
    return emb_q.semantic_search(get_db(), query_embedding, folder, limit, threshold)


def semantic_search_advanced(
    query_embedding: list[float],
    folder: str,
    limit: int,
    filters: dict,
    threshold: float = 0.5,
) -> list[dict]:
    return emb_q.semantic_search_advanced(
        get_db(), query_embedding, folder, limit, filters, threshold
    )


def get_search_suggestions(query: str, limit: int = 5) -> list[dict]:
    return email_q.get_search_suggestions(get_db(), query, limit)


def find_related_emails(uid: int, folder: str, limit: int = 5) -> list[dict]:
    return emb_q.find_related_emails(get_db(), uid, folder, limit)


def get_new_priority_emails(since, limit: int = 10) -> list[dict]:
    return email_q.get_new_priority_emails(get_db(), since, limit)


def upsert_contact(
    email: str,
    display_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    organization: str | None = None,
):
    return contact_q.upsert_contact(
        get_db(), email, display_name, first_name, last_name, organization
    )


def add_contact_interaction(
    contact_id: int,
    email_uid: int,
    email_folder: str,
    direction: str,
    subject: str,
    email_date: str,
    message_id: Optional[str] = None,
):
    return contact_q.add_contact_interaction(
        get_db(),
        contact_id,
        email_uid,
        email_folder,
        direction,
        subject,
        email_date,
        message_id,
    )


def get_all_contacts(
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "last_email_date",
):
    return contact_q.get_all_contacts(get_db(), limit, offset, search, sort_by)


def get_contact_by_email(email: str):
    return contact_q.get_contact_by_email(get_db(), email)


def get_contact_interactions(contact_id: int, limit: int = 50):
    return contact_q.get_contact_interactions(get_db(), contact_id, limit)


def get_frequent_contacts(limit: int = 20, exclude_email: str | None = None):
    return contact_q.get_frequent_contacts(get_db(), limit, exclude_email)


def get_recent_contacts(limit: int = 20):
    return contact_q.get_recent_contacts(get_db(), limit)


def search_contacts_autocomplete(query: str, limit: int = 10):
    return contact_q.search_contacts_autocomplete(get_db(), query, limit)


def update_contact_vip_status(contact_id: int, is_vip: bool):
    return contact_q.update_contact_vip_status(get_db(), contact_id, is_vip)


def add_contact_note(contact_id: int, note: str):
    return contact_q.add_contact_note(get_db(), contact_id, note)


def get_contact_notes(contact_id: int):
    return contact_q.get_contact_notes(get_db(), contact_id)
