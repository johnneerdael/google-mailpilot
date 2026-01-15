from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from workspace_secretary.db import schema
from workspace_secretary.db.types import DatabaseConnection, DatabaseInterface
from workspace_secretary.db.queries import emails as email_q
from workspace_secretary.db.queries import embeddings as emb_q
from workspace_secretary.db.queries import contacts as contact_q
from workspace_secretary.db.queries import calendar as cal_q
from workspace_secretary.db.queries import preferences as pref_q
from workspace_secretary.db.queries import mutations as mut_q

logger = logging.getLogger(__name__)


class PostgresDatabase(DatabaseInterface):
    def _expected_embedding_type(self) -> str:
        return f"{self._vector_type}({self.embedding_dimensions})"

    def _get_embedding_column_type_name(self, cur: Any) -> str:
        cur.execute(
            """
            SELECT a.atttypid::regtype::text AS type_name
            FROM pg_attribute a
            WHERE a.attrelid = 'email_embeddings'::regclass
              AND a.attname = 'embedding'
              AND NOT a.attisdropped
            """
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("email_embeddings.embedding column not found")
        return str(row[0])

    def _ensure_embeddings_schema(self, cur: Any) -> None:
        expected_type = self._expected_embedding_type()

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS email_embeddings (
                email_uid INTEGER NOT NULL,
                email_folder TEXT NOT NULL,
                embedding {expected_type},
                model TEXT,
                content_hash TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (email_uid, email_folder),
                FOREIGN KEY (email_uid, email_folder) REFERENCES emails(uid, folder) ON DELETE CASCADE
            )
            """
        )

        actual_type_name = self._get_embedding_column_type_name(cur)
        expected_base_type = expected_type.split("(", 1)[0]

        if actual_type_name != expected_base_type:
            cur.execute("DROP INDEX IF EXISTS idx_embeddings_vector")
            cur.execute(
                f"""
                ALTER TABLE email_embeddings
                ALTER COLUMN embedding TYPE {expected_type}
                USING embedding::{expected_type}
                """
            )

    def _ensure_embeddings_index(self, cur: Any) -> None:
        type_name = self._get_embedding_column_type_name(cur)
        ops = "halfvec_ip_ops" if type_name == "halfvec" else "vector_ip_ops"

        cur.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'email_embeddings'
              AND indexname = 'idx_embeddings_vector'
            """
        )
        row = cur.fetchone()
        existing_def = str(row[0]) if row else None
        expected_fragment = f"USING hnsw (embedding {ops})"

        if existing_def and expected_fragment not in existing_def:
            cur.execute("DROP INDEX IF EXISTS idx_embeddings_vector")

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_embeddings_vector
            ON email_embeddings USING hnsw (embedding {ops})
            """
        )

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
                schema.initialize_core_schema(
                    cur, self._vector_type, self.embedding_dimensions
                )
                self._ensure_embeddings_schema(cur)
                schema.initialize_contacts_schema(cur)
                schema.initialize_calendar_schema(cur)
                schema.initialize_mutation_journal(cur)
                schema.create_indexes(cur, self._vector_type)
                self._ensure_embeddings_index(cur)
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
        security_score: int = 100,
        warning_type: Optional[str] = None,
    ) -> None:
        return email_q.upsert_email(
            self,
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
            gmail_thread_id,
            gmail_msgid,
            gmail_labels,
            has_attachments,
            attachment_filenames,
            auth_results_raw,
            spf,
            dkim,
            dmarc,
            is_suspicious_sender,
            suspicious_sender_signals,
            security_score,
            warning_type,
        )

    def update_email_flags(
        self,
        uid: int,
        folder: str,
        flags: str,
        is_unread: bool,
        modseq: int,
        gmail_labels: Optional[list[str]] = None,
    ) -> None:
        return email_q.update_email_flags(
            self, uid, folder, flags, is_unread, modseq, gmail_labels
        )

    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        return email_q.get_email(self, uid, folder)

    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        return email_q.get_emails_by_uids(self, uids, folder)

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
        return email_q.search_emails(
            self,
            folder,
            is_unread,
            from_addr,
            to_addr,
            subject_contains,
            body_contains,
            limit,
        )

    def delete_email(self, uid: int, folder: str) -> None:
        return email_q.delete_email(self, uid, folder)

    def mark_email_read(self, uid: int, folder: str, is_read: bool) -> None:
        return email_q.mark_email_read(self, uid, folder, is_read)

    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        return email_q.get_folder_state(self, folder)

    def save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        return email_q.save_folder_state(
            self, folder, uidvalidity, uidnext, highestmodseq
        )

    def clear_folder(self, folder: str) -> int:
        return email_q.clear_folder(self, folder)

    def create_mutation(
        self,
        email_uid: int,
        email_folder: str,
        action: str,
        params: Optional[dict] = None,
        pre_state: Optional[dict] = None,
    ) -> int:
        return mut_q.create_mutation(
            self, email_uid, email_folder, action, params, pre_state
        )

    def update_mutation_status(
        self, mutation_id: int, status: str, error: Optional[str] = None
    ) -> None:
        return mut_q.update_mutation_status(self, mutation_id, status, error)

    def get_pending_mutations(self, email_uid: int, email_folder: str) -> list[dict]:
        return mut_q.get_pending_mutations(self, email_uid, email_folder)

    def get_mutation(self, mutation_id: int) -> Optional[dict]:
        return mut_q.get_mutation(self, mutation_id)

    def log_sync_error(
        self,
        error_type: str,
        error_message: str,
        folder: Optional[str] = None,
        email_uid: Optional[int] = None,
    ) -> None:
        return email_q.log_sync_error(
            self, error_type, error_message, folder, email_uid
        )

    def get_synced_uids(self, folder: str) -> list[int]:
        return email_q.get_synced_uids(self, folder)

    def count_emails(self, folder: str) -> int:
        return email_q.count_emails(self, folder)

    def get_synced_folders(self) -> list[dict[str, Any]]:
        return email_q.get_synced_folders(self)

    def upsert_embedding(
        self,
        uid: int,
        folder: str,
        embedding: list[float],
        model: str,
        content_hash: str,
    ) -> None:
        return emb_q.upsert_embedding(self, uid, folder, embedding, model, content_hash)

    def count_emails_needing_embedding(self, folder: str) -> int:
        return emb_q.count_emails_needing_embedding(self, folder)

    def get_emails_needing_embedding(
        self, folder: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return emb_q.get_emails_needing_embedding(self, folder, limit)

    def get_user_preferences(self, user_id: str) -> dict[str, Any]:
        return pref_q.get_user_preferences(self, user_id)

    def upsert_user_preferences(self, user_id: str, prefs: dict[str, Any]) -> None:
        return pref_q.upsert_user_preferences(self, user_id, prefs)

    def ensure_calendar_schema(self) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calendar_sync_state (
                        calendar_id TEXT PRIMARY KEY,
                        sync_token TEXT,
                        window_start TEXT NOT NULL,
                        window_end TEXT NOT NULL,
                        last_full_sync_at TIMESTAMPTZ,
                        last_incremental_sync_at TIMESTAMPTZ,
                        status TEXT NOT NULL DEFAULT 'ok',
                        last_error TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calendar_events_cache (
                        calendar_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        etag TEXT,
                        updated TIMESTAMPTZ,
                        status TEXT,
                        start_ts_utc TIMESTAMPTZ,
                        end_ts_utc TIMESTAMPTZ,
                        start_date DATE,
                        end_date DATE,
                        is_all_day BOOLEAN DEFAULT FALSE,
                        summary TEXT,
                        location TEXT,
                        local_status TEXT NOT NULL DEFAULT 'synced',
                        raw_json JSONB NOT NULL,
                        PRIMARY KEY (calendar_id, event_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS calendar_outbox (
                        id UUID PRIMARY KEY,
                        op_type TEXT NOT NULL,
                        calendar_id TEXT NOT NULL,
                        event_id TEXT,
                        local_temp_id TEXT,
                        payload_json JSONB NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        last_attempt_at TIMESTAMPTZ,
                        error TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cal_events_start_ts ON calendar_events_cache(calendar_id, start_ts_utc)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cal_events_start_date ON calendar_events_cache(calendar_id, start_date)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cal_outbox_status ON calendar_outbox(status, created_at)"
                )
                conn.commit()

    def upsert_calendar_sync_state(
        self,
        calendar_id: str,
        window_start: str,
        window_end: str,
        sync_token: Optional[str],
        status: str = "ok",
        last_error: Optional[str] = None,
        last_full_sync_at: Optional[str] = None,
        last_incremental_sync_at: Optional[str] = None,
    ) -> None:
        return cal_q.upsert_calendar_sync_state(
            self,
            calendar_id,
            window_start,
            window_end,
            sync_token,
            status,
            last_error,
            last_full_sync_at,
            last_incremental_sync_at,
        )

    def get_calendar_sync_state(self, calendar_id: str) -> Optional[dict[str, Any]]:
        return cal_q.get_calendar_sync_state(self, calendar_id)

    def list_calendar_sync_states(self) -> list[dict[str, Any]]:
        return cal_q.list_calendar_sync_states(self)

    def upsert_calendar_event_cache(
        self,
        calendar_id: str,
        event_id: str,
        raw_json: dict[str, Any],
        etag: Optional[str] = None,
        updated: Optional[str] = None,
        status: Optional[str] = None,
        start_ts_utc: Optional[str] = None,
        end_ts_utc: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        is_all_day: bool = False,
        summary: Optional[str] = None,
        location: Optional[str] = None,
        local_status: str = "synced",
    ) -> None:
        return cal_q.upsert_calendar_event_cache(
            self,
            calendar_id,
            event_id,
            raw_json,
            etag,
            updated,
            status,
            start_ts_utc,
            end_ts_utc,
            start_date,
            end_date,
            is_all_day,
            summary,
            location,
            local_status,
        )

    def delete_calendar_event_cache(self, calendar_id: str, event_id: str) -> None:
        return cal_q.delete_calendar_event_cache(self, calendar_id, event_id)

    def query_calendar_events_cached(
        self,
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
    ) -> list[dict[str, Any]]:
        return cal_q.query_calendar_events_cached(
            self, calendar_ids, time_min, time_max
        )

    def enqueue_calendar_outbox(
        self,
        op_type: str,
        calendar_id: str,
        payload_json: dict[str, Any],
        event_id: Optional[str] = None,
        local_temp_id: Optional[str] = None,
    ) -> str:
        return cal_q.enqueue_calendar_outbox(
            self, op_type, calendar_id, payload_json, event_id, local_temp_id
        )

    def list_calendar_outbox(
        self, statuses: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        return cal_q.list_calendar_outbox(self, statuses)

    def update_calendar_outbox_status(
        self,
        outbox_id: str,
        status: str,
        error: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> None:
        return cal_q.update_calendar_outbox_status(
            self, outbox_id, status, error, event_id
        )


def create_database(config: Any) -> DatabaseInterface:
    postgres_config = getattr(config, "postgres", None)
    if not postgres_config:
        raise ValueError("PostgreSQL config is required (database.postgres)")

    embedding_dimensions = 1536
    if hasattr(config, "embeddings") and config.embeddings:
        embedding_dimensions = getattr(config.embeddings, "dimensions", 1536)

    return PostgresDatabase(
        host=postgres_config.host,
        port=postgres_config.port,
        database=postgres_config.database,
        user=postgres_config.user,
        password=postgres_config.password,
        ssl_mode=getattr(postgres_config, "ssl_mode", "prefer"),
        embedding_dimensions=embedding_dimensions,
    )
