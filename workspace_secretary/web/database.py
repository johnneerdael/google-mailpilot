"""
Web UI database access layer - read-only queries using shared PostgresDatabase.
"""

from typing import Optional, Any
from contextlib import contextmanager
import logging
from psycopg.rows import dict_row

from workspace_secretary.db import PostgresDatabase
from workspace_secretary.db.queries import emails as email_q
from workspace_secretary.db.queries import embeddings as emb_q
from workspace_secretary.db.queries import contacts as contact_q
from workspace_secretary.db.queries import calendar as calendar_q
from workspace_secretary.db.queries import preferences as prefs_q
from workspace_secretary.db.queries import booking_links as booking_q

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


# =============================================================================
# Calendar Functions (Read-Only)
# =============================================================================


def query_calendar_events(
    calendar_ids: list[str], time_min: str, time_max: str
) -> list[dict]:
    """Query cached calendar events in time range."""
    return calendar_q.query_calendar_events_cached(
        get_db(), calendar_ids, time_min, time_max
    )


def get_calendar_sync_state(calendar_id: str) -> Optional[dict]:
    """Get sync state for a calendar."""
    return calendar_q.get_calendar_sync_state(get_db(), calendar_id)


def get_user_calendar_preferences(user_id: str = "default") -> dict:
    """Get calendar preferences including selected calendar IDs."""
    prefs = prefs_q.get_user_preferences(get_db(), user_id)
    return prefs.get("calendar", {})


def get_calendar_selection_state(user_id: str = "default") -> dict:
    """Return selected/available calendar IDs along with sync state metadata."""
    calendar_prefs = get_user_calendar_preferences(user_id)
    preferred_ids: list[str] = calendar_prefs.get("selected_calendar_ids", []) or []

    states = calendar_q.list_calendar_sync_states(get_db())
    available_ids = [
        s["calendar_id"]
        for s in states
        if s.get("last_full_sync_at") or s.get("last_incremental_sync_at")
    ]

    if not available_ids:
        available_ids = ["primary"]

    if preferred_ids:
        selected_ids = [cid for cid in preferred_ids if cid in available_ids]
    else:
        selected_ids = ["primary"] if "primary" in available_ids else available_ids[:1]

    if not selected_ids:
        selected_ids = ["primary"] if "primary" in available_ids else available_ids

    return {
        "selected_ids": selected_ids,
        "available_ids": available_ids,
        "states": states,
    }


def get_selected_calendar_ids(user_id: str = "default") -> list[str]:
    return get_calendar_selection_state(user_id)["selected_ids"]


def get_user_calendar_events_with_state(
    user_id: str, time_min: str, time_max: str
) -> tuple[dict, list[dict]]:
    """Fetch calendar selection state and corresponding events."""
    selection_state = get_calendar_selection_state(user_id)
    events = query_calendar_events(selection_state["selected_ids"], time_min, time_max)
    return selection_state, events


def get_user_calendar_events(
    user_id: str, time_min: str, time_max: str
) -> tuple[list[str], list[dict]]:
    """Convenience helper to fetch selected IDs and their events."""
    selection_state, events = get_user_calendar_events_with_state(
        user_id, time_min, time_max
    )
    return selection_state["selected_ids"], events


def get_user_calendar_event(
    user_id: str,
    calendar_id: str,
    event_id: str,
) -> Optional[dict]:
    """Fetch a single event ensuring calendar is authorized for the user."""
    selection_state = get_calendar_selection_state(user_id)
    if calendar_id not in selection_state["selected_ids"]:
        return None
    return calendar_q.get_calendar_event_cached(get_db(), calendar_id, event_id)


# =============================================================================
# Booking Links
# =============================================================================


def get_booking_link(link_id: str) -> Optional[dict[str, Any]]:
    """Fetch a booking link definition by ID."""
    return booking_q.get_booking_link(get_db(), link_id)


def list_booking_links_for_user(
    user_id: str, include_inactive: bool = False
) -> list[dict[str, Any]]:
    return booking_q.list_booking_links_for_user(get_db(), user_id, include_inactive)


def save_booking_link(
    link_id: str,
    user_id: str,
    calendar_id: str,
    host_name: Optional[str] = None,
    meeting_title: Optional[str] = None,
    meeting_description: Optional[str] = None,
    timezone: Optional[str] = None,
    duration_minutes: int = 30,
    availability_days: int = 14,
    availability_start_hour: int = 11,
    availability_end_hour: int = 22,
    is_active: bool = True,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    booking_q.upsert_booking_link(
        get_db(),
        link_id,
        user_id,
        calendar_id,
        host_name,
        meeting_title,
        meeting_description,
        timezone,
        duration_minutes,
        availability_days,
        availability_start_hour,
        availability_end_hour,
        is_active,
        metadata,
    )


def set_booking_link_status(link_id: str, is_active: bool) -> bool:
    return booking_q.set_booking_link_status(get_db(), link_id, is_active)
