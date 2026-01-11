from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol

logger = logging.getLogger(__name__)


class DatabaseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any: ...
    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> Any: ...
    def fetchone(self) -> Optional[dict[str, Any]]: ...
    def fetchall(self) -> list[dict[str, Any]]: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class DatabaseInterface(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    @contextmanager
    def connection(self) -> Iterator[Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def supports_embeddings(self) -> bool:
        return False

    def get_synced_uids(self, folder: str) -> list[int]:
        raise NotImplementedError

    def count_emails(self, folder: str) -> int:
        raise NotImplementedError

    def upsert_embedding(
        self,
        uid: int,
        folder: str,
        embedding: list[float],
        model: str,
        content_hash: str,
    ) -> None:
        raise NotImplementedError

    def get_synced_folders(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_thread_emails(
        self, uid: int, folder: str = "INBOX"
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def semantic_search(
        self,
        query_embedding: list[float],
        folder: str = "INBOX",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def semantic_search_filtered(
        self,
        query_embedding: list[float],
        folder: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        has_attachments: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def find_similar_emails(
        self, uid: int, folder: str = "INBOX", limit: int = 5
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

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
        bcc_addr: str,
        date: Optional[str],
        internal_date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        modseq: int,
        in_reply_to: str,
        references_header: str,
        gmail_thread_id: Optional[int],
        gmail_msgid: Optional[int],
        gmail_labels: Optional[list[str]],
        has_attachments: bool,
        attachment_filenames: Optional[list[str]],
        auth_results_raw: Optional[str] = None,
        spf: Optional[str] = None,
        dkim: Optional[str] = None,
        dmarc: Optional[str] = None,
        is_suspicious_sender: bool = False,
        suspicious_sender_signals: Optional[dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_email_flags(
        self,
        uid: int,
        folder: str,
        flags: str,
        is_unread: bool,
        modseq: int,
        gmail_labels: Optional[list[str]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        raise NotImplementedError

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
        raise NotImplementedError

    @abstractmethod
    def delete_email(self, uid: int, folder: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_email_read(self, uid: int, folder: str, is_read: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_folder(self, folder: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def log_sync_error(
        self,
        error_type: str,
        error_message: str,
        folder: Optional[str] = None,
        email_uid: Optional[int] = None,
    ) -> None:
        raise NotImplementedError

    def create_mutation(
        self,
        email_uid: int,
        email_folder: str,
        action: str,
        params: Optional[dict] = None,
        pre_state: Optional[dict] = None,
    ) -> int:
        raise NotImplementedError

    def update_mutation_status(
        self, mutation_id: int, status: str, error: Optional[str] = None
    ) -> None:
        raise NotImplementedError

    def get_pending_mutations(self, email_uid: int, email_folder: str) -> list[dict]:
        raise NotImplementedError

    def get_mutation(self, mutation_id: int) -> Optional[dict]:
        raise NotImplementedError


class SqliteDatabase(DatabaseInterface):
    def __init__(self, db_path: str = "config/secretary.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def supports_embeddings(self) -> bool:
        return False

    @contextmanager
    def _get_email_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        self._init_email_db()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self._get_email_connection() as conn:
            yield conn

    def close(self) -> None:
        return

    def _init_email_db(self) -> None:
        with self._get_email_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emails (
                    uid INTEGER,
                    folder TEXT,
                    message_id TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    to_addr TEXT,
                    cc_addr TEXT,
                    bcc_addr TEXT,
                    date TEXT,
                    internal_date TEXT,
                    body_text TEXT,
                    body_html TEXT,
                    flags TEXT,
                    is_unread INTEGER,
                    is_important INTEGER,
                    size INTEGER,
                    modseq INTEGER,
                    synced_at TEXT,
                    in_reply_to TEXT,
                    references_header TEXT,
                    content_hash TEXT,
                    gmail_thread_id INTEGER,
                    gmail_msgid INTEGER,
                    gmail_labels TEXT,
                    has_attachments INTEGER DEFAULT 0,
                    attachment_filenames TEXT,
                    auth_results_raw TEXT,
                    spf TEXT,
                    dkim TEXT,
                    dmarc TEXT,
                    is_suspicious_sender INTEGER DEFAULT 0,
                    suspicious_sender_signals TEXT,
                    PRIMARY KEY (uid, folder)
                )
                """
            )

            for col_def in [
                ("auth_results_raw", "TEXT"),
                ("spf", "TEXT"),
                ("dkim", "TEXT"),
                ("dmarc", "TEXT"),
                ("is_suspicious_sender", "INTEGER DEFAULT 0"),
                ("suspicious_sender_signals", "TEXT"),
            ]:
                try:
                    conn.execute(
                        f"ALTER TABLE emails ADD COLUMN {col_def[0]} {col_def[1]}"
                    )
                except Exception:
                    pass

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

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mutation_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_uid INTEGER NOT NULL,
                    email_folder TEXT NOT NULL,
                    action TEXT NOT NULL,
                    params TEXT,
                    status TEXT DEFAULT 'PENDING',
                    pre_state TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    error TEXT,
                    FOREIGN KEY (email_uid, email_folder) REFERENCES emails(uid, folder) ON DELETE CASCADE
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value TEXT,
                    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder TEXT,
                    email_uid INTEGER,
                    error_type TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    resolution TEXT
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    prefs_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                    subject, from_addr, to_addr, body_text,
                    content='emails', content_rowid='rowid'
                )
                """
            )

            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
                    INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, body_text)
                    VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_text);
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
                    INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, body_text)
                    VALUES('delete', old.rowid, old.subject, old.from_addr, old.to_addr, old.body_text);
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
                    INSERT INTO emails_fts(emails_fts, rowid, subject, from_addr, to_addr, body_text)
                    VALUES('delete', old.rowid, old.subject, old.from_addr, old.to_addr, old.body_text);
                    INSERT INTO emails_fts(rowid, subject, from_addr, to_addr, body_text)
                    VALUES (new.rowid, new.subject, new.from_addr, new.to_addr, new.body_text);
                END
                """
            )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(folder)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_unread ON emails(is_unread)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_from ON emails(from_addr)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_content_hash ON emails(content_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_gmail_thread_id ON emails(gmail_thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_has_attachments ON emails(has_attachments)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_internal_date ON emails(internal_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emails_is_suspicious_sender ON emails(is_suspicious_sender)"
            )

            conn.commit()

    def upsert_email(
        self,
        uid: int,
        folder: str,
        message_id: Optional[str],
        subject: Optional[str],
        from_addr: str,
        to_addr: str,
        cc_addr: str,
        bcc_addr: str,
        date: Optional[str],
        internal_date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        modseq: int,
        in_reply_to: str,
        references_header: str,
        gmail_thread_id: Optional[int],
        gmail_msgid: Optional[int],
        gmail_labels: Optional[list[str]],
        has_attachments: bool,
        attachment_filenames: Optional[list[str]],
        auth_results_raw: Optional[str] = None,
        spf: Optional[str] = None,
        dkim: Optional[str] = None,
        dmarc: Optional[str] = None,
        is_suspicious_sender: bool = False,
        suspicious_sender_signals: Optional[dict[str, Any]] = None,
    ) -> None:
        import hashlib

        content = f"{subject or ''}{body_text}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        gmail_labels_str = ",".join(gmail_labels) if gmail_labels else None
        attachment_filenames_str = (
            json.dumps(attachment_filenames) if attachment_filenames else None
        )
        suspicious_sender_signals_str = (
            json.dumps(suspicious_sender_signals) if suspicious_sender_signals else None
        )

        with self._get_email_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO emails (
                    uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                    bcc_addr, date, internal_date, body_text, body_html, flags,
                    is_unread, is_important, size, modseq, synced_at, in_reply_to,
                    references_header, content_hash, gmail_thread_id, gmail_msgid,
                    gmail_labels, has_attachments, attachment_filenames,
                    auth_results_raw, spf, dkim, dmarc, is_suspicious_sender, suspicious_sender_signals
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    folder,
                    message_id,
                    subject,
                    from_addr,
                    to_addr,
                    cc_addr,
                    bcc_addr,
                    date,
                    internal_date,
                    body_text,
                    body_html,
                    flags,
                    1 if is_unread else 0,
                    1 if is_important else 0,
                    size,
                    modseq,
                    datetime.utcnow().isoformat(),
                    in_reply_to,
                    references_header,
                    content_hash,
                    gmail_thread_id,
                    gmail_msgid,
                    gmail_labels_str,
                    1 if has_attachments else 0,
                    attachment_filenames_str,
                    auth_results_raw,
                    spf,
                    dkim,
                    dmarc,
                    1 if is_suspicious_sender else 0,
                    suspicious_sender_signals_str,
                ),
            )
            conn.commit()

    def update_email_flags(
        self,
        uid: int,
        folder: str,
        flags: str,
        is_unread: bool,
        modseq: int,
        gmail_labels: Optional[list[str]] = None,
    ) -> None:
        gmail_labels_str = ",".join(gmail_labels) if gmail_labels else None

        with self._get_email_connection() as conn:
            conn.execute(
                """
                UPDATE emails SET flags = ?, is_unread = ?, modseq = ?,
                    gmail_labels = COALESCE(?, gmail_labels), synced_at = ?
                WHERE uid = ? AND folder = ?
                """,
                (
                    flags,
                    1 if is_unread else 0,
                    modseq,
                    gmail_labels_str,
                    datetime.utcnow().isoformat(),
                    uid,
                    folder,
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

    def _fts_search(
        self,
        folder: str,
        query_text: str,
        is_unread: Optional[bool],
        from_addr: Optional[str],
        to_addr: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._get_email_connection() as conn:
            fts_query = f'"{query_text}"'
            base_query = """
                SELECT e.* FROM emails e
                JOIN emails_fts ON e.rowid = emails_fts.rowid
                WHERE emails_fts MATCH ? AND e.folder = ?
            """
            params: list[Any] = [fts_query, folder]

            if is_unread is not None:
                base_query += " AND e.is_unread = ?"
                params.append(1 if is_unread else 0)

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
        if body_contains:
            return self._fts_search(
                folder, body_contains, is_unread, from_addr, to_addr, limit
            )

        query = "SELECT * FROM emails WHERE folder = ?"
        params: list[Any] = [folder]

        if is_unread is not None:
            query += " AND is_unread = ?"
            params.append(1 if is_unread else 0)

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

    def create_mutation(
        self,
        email_uid: int,
        email_folder: str,
        action: str,
        params: Optional[dict] = None,
        pre_state: Optional[dict] = None,
    ) -> int:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mutation_journal (email_uid, email_folder, action, params, pre_state)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    email_uid,
                    email_folder,
                    action,
                    json.dumps(params) if params else None,
                    json.dumps(pre_state) if pre_state else None,
                ),
            )
            conn.commit()
            last_id = cursor.lastrowid
            return int(last_id) if last_id is not None else 0

    def update_mutation_status(
        self, mutation_id: int, status: str, error: Optional[str] = None
    ) -> None:
        with self._get_email_connection() as conn:
            conn.execute(
                """
                UPDATE mutation_journal
                SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, error, mutation_id),
            )
            conn.commit()

    def get_pending_mutations(self, email_uid: int, email_folder: str) -> list[dict]:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM mutation_journal
                WHERE email_uid = ? AND email_folder = ? AND status = 'PENDING'
                ORDER BY created_at
                """,
                (email_uid, email_folder),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_mutation(self, mutation_id: int) -> Optional[dict]:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM mutation_journal WHERE id = ?", (mutation_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def log_sync_error(
        self,
        error_type: str,
        error_message: str,
        folder: Optional[str] = None,
        email_uid: Optional[int] = None,
    ) -> None:
        with self._get_email_connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_errors (folder, email_uid, error_type, error_message)
                VALUES (?, ?, ?, ?)
                """,
                (folder, email_uid, error_type, error_message),
            )
            conn.commit()

    def get_synced_uids(self, folder: str) -> list[int]:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT uid FROM emails WHERE folder = ?",
                (folder,),
            )
            return [int(row[0]) for row in cursor.fetchall()]

    def count_emails(self, folder: str) -> int:
        with self._get_email_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM emails WHERE folder = ?",
                (folder,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def upsert_embedding(
        self,
        uid: int,
        folder: str,
        embedding: list[float],
        model: str,
        content_hash: str,
    ) -> None:
        raise NotImplementedError


class PostgresDatabase(DatabaseInterface):
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
        super().__init__()

        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.ssl_mode = ssl_mode
        self.embedding_dimensions = embedding_dimensions
        self._pool: Any = None
        self._vector_type = "halfvec" if embedding_dimensions > 2000 else "vector"
        self._vector_ops = (
            "halfvec_ip_ops" if embedding_dimensions > 2000 else "vector_ip_ops"
        )

    def supports_embeddings(self) -> bool:
        return True

    def _get_connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.ssl_mode}"

    def initialize(self) -> None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            raise ImportError(
                "PostgreSQL support requires psycopg[binary] and psycopg_pool. Install with: pip install 'psycopg[binary]' psycopg_pool"
            )

        self._pool = ConnectionPool(
            self._get_connection_string(), min_size=1, max_size=10
        )

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
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
                        bcc_addr TEXT,
                        date TIMESTAMPTZ,
                        internal_date TIMESTAMPTZ,
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
                        content_hash TEXT,
                        gmail_thread_id BIGINT,
                        gmail_msgid BIGINT,
                        gmail_labels JSONB,
                        has_attachments BOOLEAN DEFAULT FALSE,
                        attachment_filenames JSONB,
                        auth_results_raw TEXT,
                        spf TEXT,
                        dkim TEXT,
                        dmarc TEXT,
                        is_suspicious_sender BOOLEAN DEFAULT FALSE,
                        suspicious_sender_signals JSONB,
                        PRIMARY KEY (uid, folder)
                    )
                    """
                )

                cur.execute(
                    "ALTER TABLE emails ADD COLUMN IF NOT EXISTS auth_results_raw TEXT"
                )
                cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS spf TEXT")
                cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS dkim TEXT")
                cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS dmarc TEXT")
                cur.execute(
                    "ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_suspicious_sender BOOLEAN DEFAULT FALSE"
                )
                cur.execute(
                    "ALTER TABLE emails ADD COLUMN IF NOT EXISTS suspicious_sender_signals JSONB"
                )
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
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mutation_journal (
                        id SERIAL PRIMARY KEY,
                        email_uid INTEGER NOT NULL,
                        email_folder TEXT NOT NULL,
                        action TEXT NOT NULL,
                        params JSONB,
                        status TEXT DEFAULT 'PENDING',
                        pre_state JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        error TEXT,
                        FOREIGN KEY (email_uid, email_folder) REFERENCES emails(uid, folder) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_health (
                        id SERIAL PRIMARY KEY,
                        component TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        value TEXT,
                        recorded_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sync_errors (
                        id SERIAL PRIMARY KEY,
                        folder TEXT,
                        email_uid INTEGER,
                        error_type TEXT NOT NULL,
                        error_message TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        resolved_at TIMESTAMPTZ,
                        resolution TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id TEXT PRIMARY KEY,
                        prefs_json TEXT NOT NULL,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS email_embeddings (
                        email_uid INTEGER NOT NULL,
                        email_folder TEXT NOT NULL,
                        embedding {self._vector_type}({self.embedding_dimensions}),
                        model TEXT,
                        content_hash TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (email_uid, email_folder),
                        FOREIGN KEY (email_uid, email_folder) REFERENCES emails(uid, folder) ON DELETE CASCADE
                    )
                    """
                )
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
                    "CREATE INDEX IF NOT EXISTS idx_emails_gmail_thread_id ON emails(gmail_thread_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_gmail_labels ON emails USING gin(gmail_labels)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_has_attachments ON emails(has_attachments) WHERE has_attachments = true"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_internal_date ON emails(internal_date)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_emails_is_suspicious_sender ON emails(is_suspicious_sender)"
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_embeddings_vector
                    ON email_embeddings USING hnsw (embedding {self._vector_ops})
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_emails_fts
                    ON emails USING gin(to_tsvector('english', COALESCE(subject, '') || ' ' || COALESCE(body_text, '')))
                    """
                )
                conn.commit()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if not self._pool:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        if self._pool:
            self._pool.close()
            self._pool = None

    def upsert_email(
        self,
        uid: int,
        folder: str,
        message_id: Optional[str],
        subject: Optional[str],
        from_addr: str,
        to_addr: str,
        cc_addr: str,
        bcc_addr: str,
        date: Optional[str],
        internal_date: Optional[str],
        body_text: str,
        body_html: str,
        flags: str,
        is_unread: bool,
        is_important: bool,
        size: int,
        modseq: int,
        in_reply_to: str,
        references_header: str,
        gmail_thread_id: Optional[int],
        gmail_msgid: Optional[int],
        gmail_labels: Optional[list[str]],
        has_attachments: bool,
        attachment_filenames: Optional[list[str]],
        auth_results_raw: Optional[str] = None,
        spf: Optional[str] = None,
        dkim: Optional[str] = None,
        dmarc: Optional[str] = None,
        is_suspicious_sender: bool = False,
        suspicious_sender_signals: Optional[dict[str, Any]] = None,
    ) -> None:
        import hashlib

        content = f"{subject or ''}{body_text}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        gmail_labels_json = json.dumps(gmail_labels) if gmail_labels else None
        attachment_filenames_json = (
            json.dumps(attachment_filenames) if attachment_filenames else None
        )
        suspicious_sender_signals_json = (
            json.dumps(suspicious_sender_signals) if suspicious_sender_signals else None
        )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO emails (
                        uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                        bcc_addr, date, internal_date, body_text, body_html, flags,
                        is_unread, is_important, size, modseq, synced_at, in_reply_to,
                        references_header, content_hash, gmail_thread_id, gmail_msgid,
                        gmail_labels, has_attachments, attachment_filenames,
                        auth_results_raw, spf, dkim, dmarc, is_suspicious_sender, suspicious_sender_signals
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (uid, folder) DO UPDATE SET
                        message_id = EXCLUDED.message_id,
                        subject = EXCLUDED.subject,
                        from_addr = EXCLUDED.from_addr,
                        to_addr = EXCLUDED.to_addr,
                        cc_addr = EXCLUDED.cc_addr,
                        bcc_addr = EXCLUDED.bcc_addr,
                        date = EXCLUDED.date,
                        internal_date = EXCLUDED.internal_date,
                        body_text = EXCLUDED.body_text,
                        body_html = EXCLUDED.body_html,
                        flags = EXCLUDED.flags,
                        is_unread = EXCLUDED.is_unread,
                        is_important = EXCLUDED.is_important,
                        size = EXCLUDED.size,
                        modseq = EXCLUDED.modseq,
                        synced_at = NOW(),
                        in_reply_to = EXCLUDED.in_reply_to,
                        references_header = EXCLUDED.references_header,
                        content_hash = EXCLUDED.content_hash,
                        gmail_thread_id = EXCLUDED.gmail_thread_id,
                        gmail_msgid = EXCLUDED.gmail_msgid,
                        gmail_labels = EXCLUDED.gmail_labels,
                        has_attachments = EXCLUDED.has_attachments,
                        attachment_filenames = EXCLUDED.attachment_filenames,
                        auth_results_raw = EXCLUDED.auth_results_raw,
                        spf = EXCLUDED.spf,
                        dkim = EXCLUDED.dkim,
                        dmarc = EXCLUDED.dmarc,
                        is_suspicious_sender = EXCLUDED.is_suspicious_sender,
                        suspicious_sender_signals = EXCLUDED.suspicious_sender_signals
                    """,
                    (
                        uid,
                        folder,
                        message_id,
                        subject,
                        from_addr,
                        to_addr,
                        cc_addr,
                        bcc_addr,
                        date,
                        internal_date,
                        body_text,
                        body_html,
                        flags,
                        is_unread,
                        is_important,
                        size,
                        modseq,
                        in_reply_to,
                        references_header,
                        content_hash,
                        gmail_thread_id,
                        gmail_msgid,
                        gmail_labels_json,
                        has_attachments,
                        attachment_filenames_json,
                        auth_results_raw,
                        spf,
                        dkim,
                        dmarc,
                        is_suspicious_sender,
                        suspicious_sender_signals_json,
                    ),
                )
                conn.commit()

    def update_email_flags(
        self,
        uid: int,
        folder: str,
        flags: str,
        is_unread: bool,
        modseq: int,
        gmail_labels: Optional[list[str]] = None,
    ) -> None:
        gmail_labels_json = json.dumps(gmail_labels) if gmail_labels else None

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE emails SET flags = %s, is_unread = %s, modseq = %s,
                        gmail_labels = COALESCE(%s, gmail_labels), synced_at = NOW()
                    WHERE uid = %s AND folder = %s
                    """,
                    (flags, is_unread, modseq, gmail_labels_json, uid, folder),
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

        query = f"SELECT * FROM emails WHERE {' AND '.join(conditions)} ORDER BY date DESC LIMIT %s"
        params.append(limit)

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
                if is_read:
                    cur.execute(
                        """
                        UPDATE emails SET is_unread = false
                        WHERE uid = %s AND folder = %s
                        """,
                        (uid, folder),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE emails SET is_unread = true
                        WHERE uid = %s AND folder = %s
                        """,
                        (uid, folder),
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
                deleted = cur.rowcount
                conn.commit()
                return deleted

    def create_mutation(
        self,
        email_uid: int,
        email_folder: str,
        action: str,
        params: Optional[dict] = None,
        pre_state: Optional[dict] = None,
    ) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mutation_journal (email_uid, email_folder, action, params, pre_state)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        email_uid,
                        email_folder,
                        action,
                        json.dumps(params) if params else None,
                        json.dumps(pre_state) if pre_state else None,
                    ),
                )
                mutation_id = cur.fetchone()[0]
                conn.commit()
                return int(mutation_id)

    def update_mutation_status(
        self, mutation_id: int, status: str, error: Optional[str] = None
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mutation_journal
                    SET status = %s, error = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, error, mutation_id),
                )
                conn.commit()

    def get_pending_mutations(self, email_uid: int, email_folder: str) -> list[dict]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM mutation_journal
                    WHERE email_uid = %s AND email_folder = %s AND status = 'PENDING'
                    ORDER BY created_at
                    """,
                    (email_uid, email_folder),
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_mutation(self, mutation_id: int) -> Optional[dict]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM mutation_journal WHERE id = %s", (mutation_id,)
                )
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                return None

    def log_sync_error(
        self,
        error_type: str,
        error_message: str,
        folder: Optional[str] = None,
        email_uid: Optional[int] = None,
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_errors (folder, email_uid, error_type, error_message)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (folder, email_uid, error_type, error_message),
                )
                conn.commit()

    def get_synced_uids(self, folder: str) -> list[int]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT uid FROM emails WHERE folder = %s", (folder,))
                rows = cur.fetchall()
                return [int(row[0]) for row in rows]

    def count_emails(self, folder: str) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM emails WHERE folder = %s", (folder,))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def upsert_embedding(
        self,
        uid: int,
        folder: str,
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
                    (uid, folder, embedding, model, content_hash),
                )
                conn.commit()


def create_database(config: Any) -> DatabaseInterface:
    backend = getattr(config, "backend", "sqlite")
    if backend == "postgres":
        return PostgresDatabase(
            host=config.host,
            port=config.port,
            database=config.database,
            user=config.user,
            password=config.password,
            ssl_mode=getattr(config, "ssl_mode", "prefer"),
            embedding_dimensions=getattr(config, "embedding_dimensions", 1536),
        )

    return SqliteDatabase(db_path=getattr(config, "path", "config/secretary.db"))
