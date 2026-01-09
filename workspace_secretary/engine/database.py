"""
Abstract database interface for swappable backends (SQLite/PostgreSQL).

This module provides a unified interface for database operations, allowing
the engine to use either SQLite (default) or PostgreSQL with pgvector
for semantic search capabilities.
"""

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol

logger = logging.getLogger(__name__)


class DatabaseConnection(Protocol):
    """Protocol for database connections."""

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> Any: ...
    def fetchone(self) -> Optional[dict[str, Any]]: ...
    def fetchall(self) -> list[dict[str, Any]]: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class DatabaseInterface(ABC):
    """Abstract base class for database backends."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema."""
        pass

    @abstractmethod
    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Get a database connection context manager."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close any persistent connections."""
        pass

    # Email operations
    @abstractmethod
    def upsert_email(
        self,
        uid: int,
        folder: str,
        message_id: Optional[str],
        subject: Optional[str],
        from_addr: str,
        to_addr: str,
        cc_addr: str,
        date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        in_reply_to: str,
        references_header: str,
    ) -> None:
        """Insert or update an email record."""
        pass

    @abstractmethod
    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        """Get a single email by UID and folder."""
        pass

    @abstractmethod
    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        """Get multiple emails by UIDs."""
        pass

    @abstractmethod
    def search_emails(
        self,
        folder: str = "INBOX",
        is_unread: Optional[bool] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject_contains: Optional[str] = None,
        body_contains: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search emails with filters."""
        pass

    @abstractmethod
    def delete_email(self, uid: int, folder: str) -> None:
        """Delete an email from the database."""
        pass

    @abstractmethod
    def mark_email_read(self, uid: int, folder: str, is_read: bool) -> None:
        """Mark an email as read or unread."""
        pass

    @abstractmethod
    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        """Get sync state for a folder."""
        pass

    @abstractmethod
    def save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        """Save sync state for a folder."""
        pass

    @abstractmethod
    def clear_folder(self, folder: str) -> int:
        """Clear all emails from a folder. Returns count deleted."""
        pass

    @abstractmethod
    def get_synced_folders(self) -> list[dict[str, Any]]:
        """Get list of all synced folders with their state."""
        pass

    @abstractmethod
    def get_thread_emails(self, uid: int, folder: str) -> list[dict[str, Any]]:
        """Get all emails in a thread based on References/In-Reply-To headers."""
        pass

    # Calendar operations
    @abstractmethod
    def upsert_calendar(
        self,
        calendar_id: str,
        summary: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
        access_role: Optional[str] = None,
    ) -> None:
        """Insert or update a calendar."""
        pass

    @abstractmethod
    def upsert_event(self, event: dict[str, Any], calendar_id: str) -> None:
        """Insert or update a calendar event."""
        pass

    @abstractmethod
    def delete_event(self, event_id: str) -> None:
        """Delete a calendar event."""
        pass

    @abstractmethod
    def get_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get calendar events with optional time range filter."""
        pass

    @abstractmethod
    def get_sync_token(self, calendar_id: str) -> Optional[str]:
        """Get calendar sync token."""
        pass

    @abstractmethod
    def update_sync_token(self, calendar_id: str, sync_token: str) -> None:
        """Update calendar sync token."""
        pass

    # Embedding operations (optional - only for PostgreSQL with pgvector)
    def supports_embeddings(self) -> bool:
        """Check if this backend supports vector embeddings."""
        return False

    def upsert_embedding(
        self,
        email_uid: int,
        email_folder: str,
        embedding: list[float],
        model: str,
        content_hash: str,
    ) -> None:
        """Store embedding for an email. Only available with pgvector."""
        raise NotImplementedError("Embeddings not supported by this backend")

    def get_embedding(
        self, email_uid: int, email_folder: str
    ) -> Optional[dict[str, Any]]:
        """Get embedding for an email."""
        raise NotImplementedError("Embeddings not supported by this backend")

    def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 20,
        folder: Optional[str] = None,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search emails by semantic similarity. Only available with pgvector."""
        raise NotImplementedError("Embeddings not supported by this backend")

    def find_similar_emails(
        self, email_uid: int, email_folder: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Find emails similar to a given email. Only available with pgvector."""
        raise NotImplementedError("Embeddings not supported by this backend")

    def get_emails_needing_embedding(
        self, folder: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get emails that don't have embeddings yet."""
        raise NotImplementedError("Embeddings not supported by this backend")


class SqliteDatabase(DatabaseInterface):
    """SQLite database backend with FTS5 for keyword search."""

    def __init__(
        self,
        email_cache_path: str = "config/email_cache.db",
        calendar_cache_path: str = "config/calendar_cache.db",
    ):
        import sqlite3

        self.email_db_path = Path(email_cache_path)
        self.calendar_db_path = Path(calendar_cache_path)
        self._sqlite3 = sqlite3

    def initialize(self) -> None:
        """Initialize both email and calendar databases."""
        self._init_email_db()
        self._init_calendar_db()

    def _init_email_db(self) -> None:
        """Initialize email database schema."""
        self.email_db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_email_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emails (
                    uid INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    message_id TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    to_addr TEXT,
                    cc_addr TEXT,
                    date TEXT,
                    body_text TEXT,
                    body_html TEXT,
                    flags TEXT,
                    is_unread BOOLEAN,
                    is_important BOOLEAN,
                    size INTEGER,
                    modseq INTEGER,
                    synced_at TEXT,
                    in_reply_to TEXT,
                    references_header TEXT,
                    thread_root_uid INTEGER,
                    thread_parent_uid INTEGER,
                    thread_depth INTEGER DEFAULT 0,
                    content_hash TEXT,
                    PRIMARY KEY (uid, folder)
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folder_state (
                    folder TEXT PRIMARY KEY,
                    uidvalidity INTEGER,
                    uidnext INTEGER,
                    highestmodseq INTEGER,
                    last_sync TEXT
                )
                """
            )

            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_folder ON emails(folder)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_unread ON emails(is_unread)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON emails(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_from ON emails(from_addr)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_id ON emails(message_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_hash ON emails(content_hash)"
            )

            # Create FTS5 virtual table for full-text search
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                    subject, body_text, from_addr, to_addr,
                    content='emails',
                    content_rowid='rowid'
                )
                """
            )

            conn.commit()
            logger.info(f"Email database initialized at {self.email_db_path}")

    def _init_calendar_db(self) -> None:
        """Initialize calendar database schema."""
        self.calendar_db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_calendar_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS calendars (
                    id TEXT PRIMARY KEY,
                    summary TEXT,
                    description TEXT,
                    timezone TEXT,
                    access_role TEXT,
                    sync_token TEXT,
                    last_sync TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    calendar_id TEXT NOT NULL,
                    summary TEXT,
                    description TEXT,
                    location TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    all_day INTEGER DEFAULT 0,
                    status TEXT,
                    organizer_email TEXT,
                    recurrence TEXT,
                    recurring_event_id TEXT,
                    html_link TEXT,
                    hangout_link TEXT,
                    created TEXT,
                    updated TEXT,
                    etag TEXT,
                    raw_json TEXT,
                    FOREIGN KEY (calendar_id) REFERENCES calendars(id)
                );

                CREATE TABLE IF NOT EXISTS attendees (
                    event_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    display_name TEXT,
                    response_status TEXT,
                    is_organizer INTEGER DEFAULT 0,
                    is_self INTEGER DEFAULT 0,
                    PRIMARY KEY (event_id, email),
                    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_events_calendar ON events(calendar_id);
                CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
                CREATE INDEX IF NOT EXISTS idx_events_end ON events(end_time);
                CREATE INDEX IF NOT EXISTS idx_attendees_email ON attendees(email);
                """
            )
            conn.commit()
            logger.info(f"Calendar database initialized at {self.calendar_db_path}")

    @contextmanager
    def _get_email_connection(self) -> Iterator[Any]:
        """Get email database connection."""
        conn = self._sqlite3.connect(str(self.email_db_path))
        conn.row_factory = self._sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _get_calendar_connection(self) -> Iterator[Any]:
        """Get calendar database connection."""
        conn = self._sqlite3.connect(str(self.calendar_db_path))
        conn.row_factory = self._sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Get email database connection (default)."""
        with self._get_email_connection() as conn:
            yield conn

    def close(self) -> None:
        """SQLite connections are managed per-operation."""
        pass

    # Email operations
    def upsert_email(
        self,
        uid: int,
        folder: str,
        message_id: Optional[str],
        subject: Optional[str],
        from_addr: str,
        to_addr: str,
        cc_addr: str,
        date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        in_reply_to: str,
        references_header: str,
    ) -> None:
        import hashlib

        # Generate content hash for deduplication and embedding tracking
        content = f"{subject or ''}{body_text}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        with self._get_email_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO emails (
                    uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                    date, body_text, body_html, flags, is_unread, is_important,
                    size, synced_at, in_reply_to, references_header, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    folder,
                    message_id,
                    subject,
                    from_addr,
                    to_addr,
                    cc_addr,
                    date,
                    body_text,
                    body_html,
                    flags,
                    is_unread,
                    is_important,
                    size,
                    datetime.utcnow().isoformat(),
                    in_reply_to,
                    references_header,
                    content_hash,
                ),
            )
            conn.commit()

    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM emails WHERE uid = ? AND folder = ?", (uid, folder)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        if not uids:
            return []
        with self._get_email_connection() as conn:
            placeholders = ",".join("?" * len(uids))
            cursor = conn.execute(
                f"SELECT * FROM emails WHERE folder = ? AND uid IN ({placeholders}) ORDER BY date DESC",
                (folder, *uids),
            )
            return [dict(row) for row in cursor.fetchall()]

    def search_emails(
        self,
        folder: str = "INBOX",
        is_unread: Optional[bool] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject_contains: Optional[str] = None,
        body_contains: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        # Use FTS5 if body_contains is specified
        if body_contains:
            return self._fts_search(
                folder, body_contains, is_unread, from_addr, to_addr, limit
            )

        query = "SELECT * FROM emails WHERE folder = ?"
        params: list[Any] = [folder]

        if is_unread is not None:
            query += " AND is_unread = ?"
            params.append(is_unread)

        if from_addr:
            query += " AND from_addr LIKE ?"
            params.append(f"%{from_addr}%")

        if to_addr:
            query += " AND to_addr LIKE ?"
            params.append(f"%{to_addr}%")

        if subject_contains:
            query += " AND subject LIKE ?"
            params.append(f"%{subject_contains}%")

        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)

        with self._get_email_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _fts_search(
        self,
        folder: str,
        query_text: str,
        is_unread: Optional[bool],
        from_addr: Optional[str],
        to_addr: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Full-text search using FTS5."""
        with self._get_email_connection() as conn:
            # Build FTS query
            fts_query = f'"{query_text}"'

            base_query = """
                SELECT e.* FROM emails e
                JOIN emails_fts ON e.rowid = emails_fts.rowid
                WHERE emails_fts MATCH ? AND e.folder = ?
            """
            params: list[Any] = [fts_query, folder]

            if is_unread is not None:
                base_query += " AND e.is_unread = ?"
                params.append(is_unread)

            if from_addr:
                base_query += " AND e.from_addr LIKE ?"
                params.append(f"%{from_addr}%")

            if to_addr:
                base_query += " AND e.to_addr LIKE ?"
                params.append(f"%{to_addr}%")

            base_query += " ORDER BY e.date DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(base_query, params)
            return [dict(row) for row in cursor.fetchall()]

    def delete_email(self, uid: int, folder: str) -> None:
        with self._get_email_connection() as conn:
            conn.execute(
                "DELETE FROM emails WHERE uid = ? AND folder = ?", (uid, folder)
            )
            conn.commit()

    def mark_email_read(self, uid: int, folder: str, is_read: bool) -> None:
        with self._get_email_connection() as conn:
            if is_read:
                conn.execute(
                    """
                    UPDATE emails SET is_unread = 0, 
                    flags = CASE WHEN flags NOT LIKE '%\\Seen%' 
                        THEN flags || ',\\Seen' ELSE flags END
                    WHERE uid = ? AND folder = ?
                    """,
                    (uid, folder),
                )
            else:
                conn.execute(
                    """
                    UPDATE emails SET is_unread = 1,
                    flags = REPLACE(flags, '\\Seen', '')
                    WHERE uid = ? AND folder = ?
                    """,
                    (uid, folder),
                )
            conn.commit()

    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state WHERE folder = ?",
                (folder,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        with self._get_email_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO folder_state (folder, uidvalidity, uidnext, highestmodseq, last_sync)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    folder,
                    uidvalidity,
                    uidnext,
                    highestmodseq,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def clear_folder(self, folder: str) -> int:
        with self._get_email_connection() as conn:
            cursor = conn.execute("DELETE FROM emails WHERE folder = ?", (folder,))
            conn.commit()
            return cursor.rowcount

    def get_synced_folders(self) -> list[dict[str, Any]]:
        """Get list of all synced folders with their state."""
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT folder, uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state ORDER BY folder"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_thread_emails(self, uid: int, folder: str) -> list[dict[str, Any]]:
        """Get all emails in a thread based on References/In-Reply-To headers."""
        with self._get_email_connection() as conn:
            # First get the email to find its message_id and references
            cursor = conn.execute(
                "SELECT message_id, in_reply_to, references_header FROM emails WHERE uid = ? AND folder = ?",
                (uid, folder),
            )
            row = cursor.fetchone()
            if not row:
                return []

            message_id = row["message_id"]
            in_reply_to = row["in_reply_to"] or ""
            references = row["references_header"] or ""

            # Collect all related message IDs
            related_ids = set()
            if message_id:
                related_ids.add(message_id)
            for ref in (in_reply_to + " " + references).split():
                ref = ref.strip()
                if ref:
                    related_ids.add(ref)

            if not related_ids:
                # No thread info, return just this email
                cursor = conn.execute(
                    "SELECT * FROM emails WHERE uid = ? AND folder = ?",
                    (uid, folder),
                )
                result = cursor.fetchone()
                return [dict(result)] if result else []

            # Find all emails that reference any of these IDs or are referenced by them
            placeholders = ",".join("?" * len(related_ids))
            query = f"""
                SELECT * FROM emails 
                WHERE message_id IN ({placeholders})
                   OR in_reply_to IN ({placeholders})
                ORDER BY date
            """
            cursor = conn.execute(query, list(related_ids) + list(related_ids))
            return [dict(row) for row in cursor.fetchall()]

    # Calendar operations
    def upsert_calendar(
        self,
        calendar_id: str,
        summary: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
        access_role: Optional[str] = None,
    ) -> None:
        with self._get_calendar_connection() as conn:
            conn.execute(
                """
                INSERT INTO calendars (id, summary, description, timezone, access_role, last_sync)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    description = excluded.description,
                    timezone = excluded.timezone,
                    access_role = excluded.access_role,
                    last_sync = excluded.last_sync
                """,
                (
                    calendar_id,
                    summary,
                    description,
                    timezone,
                    access_role,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def upsert_event(self, event: dict[str, Any], calendar_id: str) -> None:
        import json

        event_id = event.get("id")
        if not event_id:
            return

        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime") or start.get("date")
        end_time = end.get("dateTime") or end.get("date")
        all_day = "date" in start and "dateTime" not in start

        organizer = event.get("organizer", {})
        recurrence = (
            json.dumps(event.get("recurrence")) if event.get("recurrence") else None
        )

        with self._get_calendar_connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id, calendar_id, summary, description, location,
                    start_time, end_time, all_day, status, organizer_email,
                    recurrence, recurring_event_id, html_link, hangout_link,
                    created, updated, etag, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    description = excluded.description,
                    location = excluded.location,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    all_day = excluded.all_day,
                    status = excluded.status,
                    organizer_email = excluded.organizer_email,
                    recurrence = excluded.recurrence,
                    recurring_event_id = excluded.recurring_event_id,
                    html_link = excluded.html_link,
                    hangout_link = excluded.hangout_link,
                    updated = excluded.updated,
                    etag = excluded.etag,
                    raw_json = excluded.raw_json
                """,
                (
                    event_id,
                    calendar_id,
                    event.get("summary"),
                    event.get("description"),
                    event.get("location"),
                    start_time,
                    end_time,
                    1 if all_day else 0,
                    event.get("status"),
                    organizer.get("email"),
                    recurrence,
                    event.get("recurringEventId"),
                    event.get("htmlLink"),
                    event.get("hangoutLink"),
                    event.get("created"),
                    event.get("updated"),
                    event.get("etag"),
                    json.dumps(event),
                ),
            )

            # Update attendees
            conn.execute("DELETE FROM attendees WHERE event_id = ?", (event_id,))
            for attendee in event.get("attendees", []):
                conn.execute(
                    """
                    INSERT INTO attendees (event_id, email, display_name, response_status, is_organizer, is_self)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        attendee.get("email"),
                        attendee.get("displayName"),
                        attendee.get("responseStatus"),
                        1 if attendee.get("organizer") else 0,
                        1 if attendee.get("self") else 0,
                    ),
                )
            conn.commit()

    def delete_event(self, event_id: str) -> None:
        with self._get_calendar_connection() as conn:
            conn.execute("DELETE FROM attendees WHERE event_id = ?", (event_id,))
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
            conn.commit()

    def get_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        import json

        query = "SELECT * FROM events WHERE calendar_id = ?"
        params: list[Any] = [calendar_id]

        if time_min:
            query += " AND end_time >= ?"
            params.append(time_min)
        if time_max:
            query += " AND start_time <= ?"
            params.append(time_max)

        query += " ORDER BY start_time ASC LIMIT ?"
        params.append(limit)

        with self._get_calendar_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            events = []
            for row in rows:
                event = json.loads(row["raw_json"]) if row["raw_json"] else dict(row)
                events.append(event)
            return events

    def get_sync_token(self, calendar_id: str) -> Optional[str]:
        with self._get_calendar_connection() as conn:
            row = conn.execute(
                "SELECT sync_token FROM calendars WHERE id = ?", (calendar_id,)
            ).fetchone()
            return row["sync_token"] if row else None

    def update_sync_token(self, calendar_id: str, sync_token: str) -> None:
        with self._get_calendar_connection() as conn:
            conn.execute(
                "UPDATE calendars SET sync_token = ?, last_sync = ? WHERE id = ?",
                (sync_token, datetime.utcnow().isoformat(), calendar_id),
            )
            conn.commit()


class PostgresDatabase(DatabaseInterface):
    """PostgreSQL database backend with pgvector for semantic search."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "secretary",
        user: str = "secretary",
        password: str = "",
        ssl_mode: str = "prefer",
        embedding_dimensions: int = 1536,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.ssl_mode = ssl_mode
        self.embedding_dimensions = embedding_dimensions
        self._pool: Any = None

    def _get_connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.ssl_mode}"

    def initialize(self) -> None:
        """Initialize PostgreSQL schema with pgvector extension."""
        try:
            import psycopg
            from psycopg_pool import ConnectionPool
        except ImportError:
            raise ImportError(
                "PostgreSQL support requires psycopg[binary] and psycopg_pool. "
                "Install with: pip install 'psycopg[binary]' psycopg_pool"
            )

        self._pool = ConnectionPool(
            self._get_connection_string(), min_size=1, max_size=10
        )

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

                # Create emails table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS emails (
                        uid INTEGER NOT NULL,
                        folder TEXT NOT NULL,
                        message_id TEXT,
                        subject TEXT,
                        from_addr TEXT,
                        to_addr TEXT,
                        cc_addr TEXT,
                        date TIMESTAMPTZ,
                        body_text TEXT,
                        body_html TEXT,
                        flags TEXT,
                        is_unread BOOLEAN,
                        is_important BOOLEAN,
                        size INTEGER,
                        modseq BIGINT,
                        synced_at TIMESTAMPTZ DEFAULT NOW(),
                        in_reply_to TEXT,
                        references_header TEXT,
                        thread_root_uid INTEGER,
                        thread_parent_uid INTEGER,
                        thread_depth INTEGER DEFAULT 0,
                        content_hash TEXT,
                        PRIMARY KEY (uid, folder)
                    )
                    """
                )

                # Create folder_state table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS folder_state (
                        folder TEXT PRIMARY KEY,
                        uidvalidity INTEGER,
                        uidnext INTEGER,
                        highestmodseq BIGINT,
                        last_sync TIMESTAMPTZ
                    )
                    """
                )

                # Create embeddings table with vector column
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS email_embeddings (
                        email_uid INTEGER NOT NULL,
                        email_folder TEXT NOT NULL,
                        embedding vector({self.embedding_dimensions}),
                        model TEXT,
                        content_hash TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (email_uid, email_folder),
                        FOREIGN KEY (email_uid, email_folder) REFERENCES emails(uid, folder) ON DELETE CASCADE
                    )
                    """
                )

                # Create calendar tables
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calendars (
                        id TEXT PRIMARY KEY,
                        summary TEXT,
                        description TEXT,
                        timezone TEXT,
                        access_role TEXT,
                        sync_token TEXT,
                        last_sync TIMESTAMPTZ
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        calendar_id TEXT NOT NULL REFERENCES calendars(id),
                        summary TEXT,
                        description TEXT,
                        location TEXT,
                        start_time TIMESTAMPTZ,
                        end_time TIMESTAMPTZ,
                        all_day BOOLEAN DEFAULT FALSE,
                        status TEXT,
                        organizer_email TEXT,
                        recurrence JSONB,
                        recurring_event_id TEXT,
                        html_link TEXT,
                        hangout_link TEXT,
                        created TIMESTAMPTZ,
                        updated TIMESTAMPTZ,
                        etag TEXT,
                        raw_json JSONB
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS attendees (
                        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                        email TEXT NOT NULL,
                        display_name TEXT,
                        response_status TEXT,
                        is_organizer BOOLEAN DEFAULT FALSE,
                        is_self BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (event_id, email)
                    )
                    """
                )

                # Create indexes
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(folder)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_unread ON emails(is_unread)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_from ON emails(from_addr)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_content_hash ON emails(content_hash)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_calendar ON events(calendar_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time)"
                )

                # Create HNSW index for vector similarity search
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_embeddings_vector 
                    ON email_embeddings USING hnsw (embedding vector_cosine_ops)
                    """
                )

                # Create GIN index for full-text search
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_emails_fts 
                    ON emails USING gin(to_tsvector('english', COALESCE(subject, '') || ' ' || COALESCE(body_text, '')))
                    """
                )

                conn.commit()
                logger.info("PostgreSQL database initialized with pgvector")

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Get a database connection from the pool."""
        if not self._pool:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None

    # Email operations
    def upsert_email(
        self,
        uid: int,
        folder: str,
        message_id: Optional[str],
        subject: Optional[str],
        from_addr: str,
        to_addr: str,
        cc_addr: str,
        date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        in_reply_to: str,
        references_header: str,
    ) -> None:
        import hashlib

        content = f"{subject or ''}{body_text}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO emails (
                        uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                        date, body_text, body_html, flags, is_unread, is_important,
                        size, synced_at, in_reply_to, references_header, content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
                    ON CONFLICT (uid, folder) DO UPDATE SET
                        message_id = EXCLUDED.message_id,
                        subject = EXCLUDED.subject,
                        from_addr = EXCLUDED.from_addr,
                        to_addr = EXCLUDED.to_addr,
                        cc_addr = EXCLUDED.cc_addr,
                        date = EXCLUDED.date,
                        body_text = EXCLUDED.body_text,
                        body_html = EXCLUDED.body_html,
                        flags = EXCLUDED.flags,
                        is_unread = EXCLUDED.is_unread,
                        is_important = EXCLUDED.is_important,
                        size = EXCLUDED.size,
                        synced_at = NOW(),
                        in_reply_to = EXCLUDED.in_reply_to,
                        references_header = EXCLUDED.references_header,
                        content_hash = EXCLUDED.content_hash
                    """,
                    (
                        uid,
                        folder,
                        message_id,
                        subject,
                        from_addr,
                        to_addr,
                        cc_addr,
                        date,
                        body_text,
                        body_html,
                        flags,
                        is_unread,
                        is_important,
                        size,
                        in_reply_to,
                        references_header,
                        content_hash,
                    ),
                )
                conn.commit()

    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM emails WHERE uid = %s AND folder = %s", (uid, folder)
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                return None

    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        if not uids:
            return []
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM emails WHERE folder = %s AND uid = ANY(%s) ORDER BY date DESC",
                    (folder, uids),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def search_emails(
        self,
        folder: str = "INBOX",
        is_unread: Optional[bool] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject_contains: Optional[str] = None,
        body_contains: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = ["folder = %s"]
        params: list[Any] = [folder]

        if is_unread is not None:
            conditions.append("is_unread = %s")
            params.append(is_unread)

        if from_addr:
            conditions.append("from_addr ILIKE %s")
            params.append(f"%{from_addr}%")

        if to_addr:
            conditions.append("to_addr ILIKE %s")
            params.append(f"%{to_addr}%")

        if subject_contains:
            conditions.append("subject ILIKE %s")
            params.append(f"%{subject_contains}%")

        if body_contains:
            # Use PostgreSQL full-text search
            conditions.append(
                "to_tsvector('english', COALESCE(subject, '') || ' ' || COALESCE(body_text, '')) @@ plainto_tsquery('english', %s)"
            )
            params.append(body_contains)

        params.append(limit)

        query = f"""
            SELECT * FROM emails 
            WHERE {" AND ".join(conditions)}
            ORDER BY date DESC LIMIT %s
        """

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def delete_email(self, uid: int, folder: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM emails WHERE uid = %s AND folder = %s", (uid, folder)
                )
                conn.commit()

    def mark_email_read(self, uid: int, folder: str, is_read: bool) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE emails SET is_unread = %s WHERE uid = %s AND folder = %s",
                    (not is_read, uid, folder),
                )
                conn.commit()

    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state WHERE folder = %s",
                    (folder,),
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                return None

    def save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO folder_state (folder, uidvalidity, uidnext, highestmodseq, last_sync)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (folder) DO UPDATE SET
                        uidvalidity = EXCLUDED.uidvalidity,
                        uidnext = EXCLUDED.uidnext,
                        highestmodseq = EXCLUDED.highestmodseq,
                        last_sync = NOW()
                    """,
                    (folder, uidvalidity, uidnext, highestmodseq),
                )
                conn.commit()

    def clear_folder(self, folder: str) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM emails WHERE folder = %s", (folder,))
                count = cur.rowcount
                conn.commit()
                return count

    def get_synced_folders(self) -> list[dict[str, Any]]:
        """Get list of all synced folders with their state."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT folder, uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state ORDER BY folder"
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_thread_emails(self, uid: int, folder: str) -> list[dict[str, Any]]:
        """Get all emails in a thread based on References/In-Reply-To headers."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                # First get the email to find its message_id and references
                cur.execute(
                    "SELECT message_id, in_reply_to, references_header FROM emails WHERE uid = %s AND folder = %s",
                    (uid, folder),
                )
                row = cur.fetchone()
                if not row:
                    return []

                message_id, in_reply_to, references = row
                in_reply_to = in_reply_to or ""
                references = references or ""

                # Collect all related message IDs
                related_ids = set()
                if message_id:
                    related_ids.add(message_id)
                for ref in (in_reply_to + " " + references).split():
                    ref = ref.strip()
                    if ref:
                        related_ids.add(ref)

                if not related_ids:
                    # No thread info, return just this email
                    cur.execute(
                        "SELECT * FROM emails WHERE uid = %s AND folder = %s",
                        (uid, folder),
                    )
                    columns = [desc[0] for desc in cur.description]
                    row = cur.fetchone()
                    return [dict(zip(columns, row))] if row else []

                # Find all emails that reference any of these IDs
                related_list = list(related_ids)
                cur.execute(
                    """
                    SELECT * FROM emails 
                    WHERE message_id = ANY(%s)
                       OR in_reply_to = ANY(%s)
                    ORDER BY date
                    """,
                    (related_list, related_list),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    # Calendar operations
    def upsert_calendar(
        self,
        calendar_id: str,
        summary: str,
        description: Optional[str] = None,
        timezone: Optional[str] = None,
        access_role: Optional[str] = None,
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO calendars (id, summary, description, timezone, access_role, last_sync)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT(id) DO UPDATE SET
                        summary = EXCLUDED.summary,
                        description = EXCLUDED.description,
                        timezone = EXCLUDED.timezone,
                        access_role = EXCLUDED.access_role,
                        last_sync = NOW()
                    """,
                    (calendar_id, summary, description, timezone, access_role),
                )
                conn.commit()

    def upsert_event(self, event: dict[str, Any], calendar_id: str) -> None:
        import json

        event_id = event.get("id")
        if not event_id:
            return

        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime") or start.get("date")
        end_time = end.get("dateTime") or end.get("date")
        all_day = "date" in start and "dateTime" not in start

        organizer = event.get("organizer", {})
        recurrence = (
            json.dumps(event.get("recurrence")) if event.get("recurrence") else None
        )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events (
                        id, calendar_id, summary, description, location,
                        start_time, end_time, all_day, status, organizer_email,
                        recurrence, recurring_event_id, html_link, hangout_link,
                        created, updated, etag, raw_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        summary = EXCLUDED.summary,
                        description = EXCLUDED.description,
                        location = EXCLUDED.location,
                        start_time = EXCLUDED.start_time,
                        end_time = EXCLUDED.end_time,
                        all_day = EXCLUDED.all_day,
                        status = EXCLUDED.status,
                        organizer_email = EXCLUDED.organizer_email,
                        recurrence = EXCLUDED.recurrence,
                        recurring_event_id = EXCLUDED.recurring_event_id,
                        html_link = EXCLUDED.html_link,
                        hangout_link = EXCLUDED.hangout_link,
                        updated = EXCLUDED.updated,
                        etag = EXCLUDED.etag,
                        raw_json = EXCLUDED.raw_json
                    """,
                    (
                        event_id,
                        calendar_id,
                        event.get("summary"),
                        event.get("description"),
                        event.get("location"),
                        start_time,
                        end_time,
                        all_day,
                        event.get("status"),
                        organizer.get("email"),
                        recurrence,
                        event.get("recurringEventId"),
                        event.get("htmlLink"),
                        event.get("hangoutLink"),
                        event.get("created"),
                        event.get("updated"),
                        event.get("etag"),
                        json.dumps(event),
                    ),
                )

                # Update attendees
                cur.execute("DELETE FROM attendees WHERE event_id = %s", (event_id,))
                for attendee in event.get("attendees", []):
                    cur.execute(
                        """
                        INSERT INTO attendees (event_id, email, display_name, response_status, is_organizer, is_self)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event_id,
                            attendee.get("email"),
                            attendee.get("displayName"),
                            attendee.get("responseStatus"),
                            attendee.get("organizer", False),
                            attendee.get("self", False),
                        ),
                    )
                conn.commit()

    def delete_event(self, event_id: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
                conn.commit()

    def get_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        import json

        conditions = ["calendar_id = %s"]
        params: list[Any] = [calendar_id]

        if time_min:
            conditions.append("end_time >= %s")
            params.append(time_min)
        if time_max:
            conditions.append("start_time <= %s")
            params.append(time_max)

        params.append(limit)

        query = f"""
            SELECT * FROM events 
            WHERE {" AND ".join(conditions)}
            ORDER BY start_time ASC LIMIT %s
        """

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                columns = [desc[0] for desc in cur.description]
                events = []
                for row in cur.fetchall():
                    row_dict = dict(zip(columns, row))
                    if row_dict.get("raw_json"):
                        events.append(
                            json.loads(row_dict["raw_json"])
                            if isinstance(row_dict["raw_json"], str)
                            else row_dict["raw_json"]
                        )
                    else:
                        events.append(row_dict)
                return events

    def get_sync_token(self, calendar_id: str) -> Optional[str]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sync_token FROM calendars WHERE id = %s", (calendar_id,)
                )
                row = cur.fetchone()
                return row[0] if row else None

    def update_sync_token(self, calendar_id: str, sync_token: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE calendars SET sync_token = %s, last_sync = NOW() WHERE id = %s",
                    (sync_token, calendar_id),
                )
                conn.commit()

    # Embedding operations (pgvector specific)
    def supports_embeddings(self) -> bool:
        return True

    def upsert_embedding(
        self,
        email_uid: int,
        email_folder: str,
        embedding: list[float],
        model: str,
        content_hash: str,
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_embeddings (email_uid, email_folder, embedding, model, content_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email_uid, email_folder) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        model = EXCLUDED.model,
                        content_hash = EXCLUDED.content_hash,
                        created_at = NOW()
                    """,
                    (email_uid, email_folder, embedding, model, content_hash),
                )
                conn.commit()

    def get_embedding(
        self, email_uid: int, email_folder: str
    ) -> Optional[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM email_embeddings WHERE email_uid = %s AND email_folder = %s",
                    (email_uid, email_folder),
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                return None

    def semantic_search(
        self,
        query_embedding: list[float],
        limit: int = 20,
        folder: Optional[str] = None,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search emails by semantic similarity using pgvector."""
        conditions = ["1 - (ee.embedding <=> %s) >= %s"]
        params: list[Any] = [query_embedding, similarity_threshold]

        if folder:
            conditions.append("ee.email_folder = %s")
            params.append(folder)

        params.append(limit)

        query = f"""
            SELECT e.*, 1 - (ee.embedding <=> %s) as similarity
            FROM emails e
            JOIN email_embeddings ee ON e.uid = ee.email_uid AND e.folder = ee.email_folder
            WHERE {" AND ".join(conditions)}
            ORDER BY ee.embedding <=> %s
            LIMIT %s
        """

        # Add query_embedding twice more for SELECT and ORDER BY clauses
        full_params = [query_embedding] + params + [query_embedding, limit]

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT e.*, 1 - (ee.embedding <=> %s::vector) as similarity
                    FROM emails e
                    JOIN email_embeddings ee ON e.uid = ee.email_uid AND e.folder = ee.email_folder
                    WHERE 1 - (ee.embedding <=> %s::vector) >= %s
                    {"AND ee.email_folder = %s" if folder else ""}
                    ORDER BY ee.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        query_embedding,
                        query_embedding,
                        similarity_threshold,
                        *([folder] if folder else []),
                        query_embedding,
                        limit,
                    ),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def find_similar_emails(
        self, email_uid: int, email_folder: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Find emails similar to a given email."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, 1 - (ee.embedding <=> source.embedding) as similarity
                    FROM email_embeddings source
                    JOIN email_embeddings ee ON ee.email_uid != source.email_uid OR ee.email_folder != source.email_folder
                    JOIN emails e ON e.uid = ee.email_uid AND e.folder = ee.email_folder
                    WHERE source.email_uid = %s AND source.email_folder = %s
                    ORDER BY ee.embedding <=> source.embedding
                    LIMIT %s
                    """,
                    (email_uid, email_folder, limit),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_emails_needing_embedding(
        self, folder: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get emails that don't have embeddings or have outdated embeddings."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.* FROM emails e
                    LEFT JOIN email_embeddings ee ON e.uid = ee.email_uid AND e.folder = ee.email_folder
                    WHERE e.folder = %s 
                      AND (ee.email_uid IS NULL OR ee.content_hash != e.content_hash)
                    ORDER BY e.date DESC
                    LIMIT %s
                    """,
                    (folder, limit),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]


def create_database(config: Any) -> DatabaseInterface:
    """Factory function to create the appropriate database backend.

    Args:
        config: DatabaseConfig from server configuration

    Returns:
        DatabaseInterface implementation (SqliteDatabase or PostgresDatabase)
    """
    from workspace_secretary.config import DatabaseBackend

    if config.backend == DatabaseBackend.SQLITE:
        return SqliteDatabase(
            email_cache_path=config.sqlite.email_cache_path,
            calendar_cache_path=config.sqlite.calendar_cache_path,
        )
    elif config.backend == DatabaseBackend.POSTGRES:
        if not config.postgres:
            raise ValueError("PostgreSQL configuration required for postgres backend")
        return PostgresDatabase(
            host=config.postgres.host,
            port=config.postgres.port,
            database=config.postgres.database,
            user=config.postgres.user,
            password=config.postgres.password,
            ssl_mode=config.postgres.ssl_mode,
            embedding_dimensions=config.embeddings.dimensions,
        )
    else:
        raise ValueError(f"Unknown database backend: {config.backend}")
