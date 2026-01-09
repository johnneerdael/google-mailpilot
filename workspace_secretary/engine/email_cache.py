"""
Email metadata cache using SQLite for fast local queries.

This module provides a local cache for email metadata to avoid slow IMAP fetches.
It implements a "sync once, query fast" pattern where:
1. Initial sync downloads all email metadata from IMAP
2. Queries run against local SQLite database (instant)
3. Incremental updates fetch only new/changed emails
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

if TYPE_CHECKING:
    from workspace_secretary.engine.imap_sync import ImapClient
    from workspace_secretary.models import Email

logger = logging.getLogger(__name__)


class EmailCache:
    """SQLite-based cache for email metadata."""

    def __init__(self, db_path: str | Path = "config/email_cache.db"):
        """
        Initialize the email cache.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
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
            # Run migrations BEFORE creating indexes on new columns
            self._migrate_schema(conn)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_folder ON emails(folder)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_unread ON emails(is_unread)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON emails(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_from ON emails(from_addr)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_id ON emails(message_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_modseq ON emails(modseq)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_root ON emails(thread_root_uid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_in_reply_to ON emails(in_reply_to)"
            )
            conn.commit()
            logger.info(f"Email cache database initialized at {self.db_path}")

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add new columns to existing databases."""
        cursor = conn.execute("PRAGMA table_info(emails)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        migrations = [
            ("in_reply_to", "TEXT"),
            ("references_header", "TEXT"),
            ("thread_root_uid", "INTEGER"),
            ("thread_parent_uid", "INTEGER"),
            ("thread_depth", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE emails ADD COLUMN {col_name} {col_type}")
                logger.info(f"Added column {col_name} to emails table")

        conn.commit()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def sync_folder(
        self,
        client: "ImapClient",
        folder: str = "INBOX",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Sync emails from an IMAP folder to the cache using incremental sync when possible.

        Uses UIDVALIDITY to detect folder resets and UIDNEXT for incremental fetching.
        """
        logger.info(f"Starting sync for folder: {folder}")

        folder_info = client.select_folder(folder)
        current_uidvalidity = folder_info.get(b"UIDVALIDITY")
        current_uidnext = folder_info.get(b"UIDNEXT")

        stored_state = self.get_folder_state(folder)

        need_full_sync = False
        if stored_state is None:
            logger.info(f"No cached state for {folder}, performing full sync")
            need_full_sync = True
        elif stored_state.get("uidvalidity") != current_uidvalidity:
            logger.warning(
                f"UIDVALIDITY changed for {folder}, cache invalidated - full sync required"
            )
            self.clear_folder(folder)
            need_full_sync = True

        if need_full_sync:
            synced = self._full_sync(
                client, folder, current_uidvalidity, current_uidnext, progress_callback
            )
        elif stored_state is not None:
            last_uid = int(stored_state.get("uidnext", 1)) - 1
            synced = self._incremental_sync(client, folder, last_uid, progress_callback)
        else:
            synced = 0

        self._save_folder_state(
            folder, int(current_uidvalidity or 0), int(current_uidnext or 0)
        )

        backfilled = self.backfill_thread_headers(
            client, folder, progress_callback=progress_callback
        )

        if synced > 0 or backfilled > 0:
            try:
                if client.has_thread_capability("REFERENCES"):
                    logger.info(f"Building thread index using IMAP THREAD command")
                    thread_data = client.get_thread_structure(folder, "REFERENCES")
                    self.build_thread_index(folder, thread_data)
                else:
                    logger.info(f"Building thread index locally (no THREAD support)")
                    self.build_thread_index(folder)
            except Exception as e:
                logger.warning(f"Failed to build thread index: {e}")

        return synced

    def _full_sync(
        self,
        client: "ImapClient",
        folder: str,
        uidvalidity: Optional[int],
        uidnext: Optional[int],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        all_uids = client.search({"ALL": True}, folder=folder)
        total = len(all_uids)
        logger.info(f"Full sync: {total} emails in {folder}")

        if total == 0:
            return 0

        batch_size = 50
        synced = 0
        uid_list = sorted(all_uids, reverse=True)

        with self._get_connection() as conn:
            for batch_start in range(0, total, batch_size):
                batch_uids = uid_list[batch_start : batch_start + batch_size]
                batch_num = batch_start // batch_size + 1
                total_batches = (total + batch_size - 1) // batch_size
                logger.info(
                    f"[SYNC] Fetching batch {batch_num}/{total_batches} ({len(batch_uids)} emails)"
                )

                emails = client.fetch_emails(batch_uids, folder=folder)

                for uid, email in emails.items():
                    self._upsert_email(conn, uid, folder, email)
                    synced += 1

                    if progress_callback and synced % 5 == 0:
                        progress_callback(synced, total)

                conn.commit()

                highest_uid_in_batch = max(batch_uids) if batch_uids else 0
                self._save_folder_state(
                    folder, int(uidvalidity or 0), highest_uid_in_batch + 1
                )

                logger.info(
                    f"[SYNC] Progress: {synced}/{total} emails cached ({100 * synced // total}%)"
                )

        logger.info(f"[SYNC] Full sync complete: {synced} emails stored in SQLite")
        return synced

    def _incremental_sync(
        self,
        client: "ImapClient",
        folder: str,
        last_uid: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        folder_info = client.select_folder(folder)
        current_uidvalidity = folder_info.get(b"UIDVALIDITY")
        current_uidnext = folder_info.get(b"UIDNEXT")

        new_uids = client.search({"UID": f"{last_uid + 1}:*"}, folder=folder)
        new_uids = [uid for uid in new_uids if uid > last_uid]

        self._sync_deletions(client, folder)

        if not new_uids:
            logger.info(f"Incremental sync: no new emails in {folder}")
            return 0

        total = len(new_uids)
        logger.info(f"Incremental sync: {total} new emails in {folder}")

        batch_size = 50
        synced = 0

        with self._get_connection() as conn:
            for batch_start in range(0, total, batch_size):
                batch_uids = new_uids[batch_start : batch_start + batch_size]
                batch_num = batch_start // batch_size + 1
                total_batches = (total + batch_size - 1) // batch_size
                logger.info(
                    f"[SYNC] Fetching batch {batch_num}/{total_batches} ({len(batch_uids)} emails)"
                )

                emails = client.fetch_emails(batch_uids, folder=folder)

                for uid, email in emails.items():
                    self._upsert_email(conn, uid, folder, email)
                    synced += 1

                    if progress_callback and synced % 5 == 0:
                        progress_callback(synced, total)

                conn.commit()

                highest_uid_in_batch = max(batch_uids) if batch_uids else 0
                self._save_folder_state(
                    folder, int(current_uidvalidity or 0), highest_uid_in_batch + 1
                )

                logger.info(
                    f"[SYNC] Progress: {synced}/{total} emails cached ({100 * synced // total}%)"
                )

        logger.info(f"[SYNC] Incremental sync complete: {synced} new emails")
        return synced

    def _sync_deletions(self, client: "ImapClient", folder: str) -> int:
        """Remove emails from cache that no longer exist on server."""
        server_uids = set(client.search({"ALL": True}, folder=folder))

        with self._get_connection() as conn:
            cursor = conn.execute("SELECT uid FROM emails WHERE folder = ?", (folder,))
            cached_uids = {row[0] for row in cursor.fetchall()}

            deleted_uids = cached_uids - server_uids
            if deleted_uids:
                logger.info(f"Removing {len(deleted_uids)} deleted emails from cache")
                placeholders = ",".join("?" * len(deleted_uids))
                conn.execute(
                    f"DELETE FROM emails WHERE folder = ? AND uid IN ({placeholders})",
                    (folder, *deleted_uids),
                )
                conn.commit()

            return len(deleted_uids)

    def backfill_thread_headers(
        self,
        client: "ImapClient",
        folder: str = "INBOX",
        batch_size: int = 100,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Fetch In-Reply-To/References headers for emails missing thread data.

        This is a fast operation - fetches headers only, not full email bodies.
        Use after schema migration to populate thread data for existing emails.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT uid FROM emails 
                WHERE folder = ? AND (in_reply_to IS NULL OR in_reply_to = '')
                """,
                (folder,),
            )
            uids_to_backfill = [row[0] for row in cursor.fetchall()]

        if not uids_to_backfill:
            logger.info(f"[BACKFILL] No emails need thread header backfill in {folder}")
            return 0

        total = len(uids_to_backfill)
        logger.info(
            f"[BACKFILL] Fetching thread headers for {total} emails in {folder}"
        )

        updated = 0
        client.select_folder(folder, readonly=True)

        for i in range(0, total, batch_size):
            batch_uids = uids_to_backfill[i : i + batch_size]

            try:
                imap_client = client._get_client()
                fetch_data = imap_client.fetch(
                    batch_uids,
                    ["BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES MESSAGE-ID)]"],
                )

                with self._get_connection() as conn:
                    for uid, data in fetch_data.items():
                        header_bytes = data.get(
                            b"BODY[HEADER.FIELDS (IN-REPLY-TO REFERENCES MESSAGE-ID)]",
                            b"",
                        )
                        if isinstance(header_bytes, bytes):
                            header_str = header_bytes.decode("utf-8", errors="replace")
                        else:
                            header_str = str(header_bytes)

                        in_reply_to = ""
                        references_header = ""
                        message_id = ""

                        for line in header_str.split("\n"):
                            line = line.strip()
                            lower_line = line.lower()
                            if lower_line.startswith("in-reply-to:"):
                                in_reply_to = line[12:].strip()
                            elif lower_line.startswith("references:"):
                                references_header = line[11:].strip()
                            elif lower_line.startswith("message-id:"):
                                message_id = line[11:].strip()

                        conn.execute(
                            """
                            UPDATE emails SET in_reply_to = ?, references_header = ?,
                                message_id = COALESCE(NULLIF(message_id, ''), ?)
                            WHERE uid = ? AND folder = ?
                            """,
                            (in_reply_to, references_header, message_id, uid, folder),
                        )

                        updated += 1

                    conn.commit()

                if progress_callback:
                    progress_callback(updated, total)

                logger.info(f"[BACKFILL] Progress: {updated}/{total} headers fetched")

            except Exception as e:
                logger.error(f"[BACKFILL] Error fetching batch: {e}")
                continue

        if updated > 0:
            logger.info(f"[BACKFILL] Building thread index for {folder}")
            try:
                if client.has_thread_capability("REFERENCES"):
                    thread_data = client.get_thread_structure(folder, "REFERENCES")
                    self.build_thread_index(folder, thread_data)
                else:
                    self.build_thread_index(folder)
            except Exception as e:
                logger.warning(f"[BACKFILL] Failed to build thread index: {e}")

        logger.info(
            f"[BACKFILL] Complete: {updated} emails updated with thread headers"
        )
        return updated

    def get_folder_state(self, folder: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state WHERE folder = ?",
                (folder,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def _save_folder_state(
        self, folder: str, uidvalidity: int, uidnext: int, highestmodseq: int = 0
    ) -> None:
        with self._get_connection() as conn:
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

    def _upsert_email(
        self, conn: sqlite3.Connection, uid: int, folder: str, email: "Email"
    ) -> None:
        flags = email.flags

        from_addr = ""
        if email.from_:
            from_addr = (
                f"{email.from_.name} <{email.from_.address}>"
                if email.from_.name
                else email.from_.address
            )

        to_addr = ", ".join(
            f"{addr.name} <{addr.address}>" if addr.name else addr.address
            for addr in email.to
        )

        cc_addr = ", ".join(
            f"{addr.name} <{addr.address}>" if addr.name else addr.address
            for addr in email.cc
        )

        body_text = email.content.text or ""
        body_html = email.content.html or ""

        in_reply_to = email.in_reply_to or ""
        references = " ".join(email.references) if email.references else ""

        conn.execute(
            """
            INSERT OR REPLACE INTO emails (
                uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                date, body_text, body_html, flags, is_unread, is_important, size, synced_at,
                in_reply_to, references
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                folder,
                email.message_id,
                email.subject,
                from_addr,
                to_addr,
                cc_addr,
                email.date.isoformat() if email.date else None,
                body_text,
                body_html,
                ",".join(flags),
                "\\Seen" not in flags,
                "\\Flagged" in flags or "\\Important" in flags,
                len(body_text) + len(body_html),
                datetime.utcnow().isoformat(),
                in_reply_to,
                references,
            ),
        )

    def get_email_by_uid(self, uid: int, folder: str) -> Optional[dict[str, Any]]:
        """Get a single email by UID and folder."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM emails WHERE uid = ? AND folder = ?",
                (uid, folder),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_emails_by_uids(self, uids: list[int], folder: str) -> list[dict[str, Any]]:
        """Get multiple emails by UIDs."""
        if not uids:
            return []
        with self._get_connection() as conn:
            placeholders = ",".join("?" * len(uids))
            cursor = conn.execute(
                f"SELECT * FROM emails WHERE folder = ? AND uid IN ({placeholders}) ORDER BY date DESC",
                (folder, *uids),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_unread_emails(
        self, folder: str = "INBOX", limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Get unread emails from cache.

        Args:
            folder: Folder to query
            limit: Maximum number of results

        Returns:
            List of email metadata dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM emails
                WHERE folder = ? AND is_unread = 1
                ORDER BY date DESC
                LIMIT ?
                """,
                (folder, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def search_emails(
        self,
        folder: str = "INBOX",
        is_unread: Optional[bool] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject_contains: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Search emails in cache with various filters.

        Args:
            folder: Folder to search
            is_unread: Filter by read/unread status
            from_addr: Filter by sender (partial match)
            to_addr: Filter by recipient (partial match)
            subject_contains: Filter by subject (partial match)
            limit: Maximum number of results

        Returns:
            List of email metadata dictionaries
        """
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

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def mark_as_read(self, uid: int, folder: str) -> None:
        """Mark an email as read in the cache."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE emails SET is_unread = 0, flags = flags || ',\\Seen' WHERE uid = ? AND folder = ? AND is_unread = 1",
                (uid, folder),
            )
            conn.commit()

    def mark_as_unread(self, uid: int, folder: str) -> None:
        """Mark an email as unread in the cache."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE emails SET is_unread = 1, flags = REPLACE(flags, '\\Seen', '') WHERE uid = ? AND folder = ?",
                (uid, folder),
            )
            conn.commit()

    def delete_email(self, uid: int, folder: str) -> None:
        """Remove an email from the cache."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM emails WHERE uid = ? AND folder = ?", (uid, folder)
            )
            conn.commit()

    def move_email(self, uid: int, from_folder: str, to_folder: str) -> None:
        """Update folder when an email is moved."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE emails SET folder = ? WHERE uid = ? AND folder = ?",
                (to_folder, uid, from_folder),
            )
            conn.commit()

    def get_folder_stats(self, folder: str = "INBOX") -> dict[str, int]:
        """
        Get statistics for a folder.

        Returns:
            Dictionary with total, unread, important counts
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_unread = 1 THEN 1 ELSE 0 END) as unread,
                    SUM(CASE WHEN is_important = 1 THEN 1 ELSE 0 END) as important
                FROM emails
                WHERE folder = ?
                """,
                (folder,),
            )
            row = cursor.fetchone()
            return {
                "total": row[0] or 0,
                "unread": row[1] or 0,
                "important": row[2] or 0,
            }

    def clear_folder(self, folder: str) -> int:
        """
        Clear all cached emails from a folder.

        Args:
            folder: Folder to clear

        Returns:
            Number of emails deleted
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM emails WHERE folder = ?", (folder,))
            conn.commit()
            return cursor.rowcount

    def get_last_sync_time(self, folder: str) -> Optional[datetime]:
        """
        Get the last sync time for a folder.

        Returns:
            Datetime of last sync, or None if never synced
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT MAX(synced_at) FROM emails WHERE folder = ?", (folder,)
            )
            result = cursor.fetchone()[0]
            return datetime.fromisoformat(result) if result else None

    def get_thread_emails(self, uid: int, folder: str) -> list[dict[str, Any]]:
        """Get all emails in a thread by following References/In-Reply-To chains."""
        with self._get_connection() as conn:
            root_email = self.get_email_by_uid(uid, folder)
            if not root_email:
                return []

            thread_uids: set[int] = {uid}
            message_id = root_email.get("message_id", "")
            in_reply_to = root_email.get("in_reply_to", "")
            references = root_email.get("references", "")

            all_message_ids: set[str] = set()
            if message_id:
                all_message_ids.add(message_id)
            if in_reply_to:
                all_message_ids.add(in_reply_to)
            if references:
                all_message_ids.update(references.split())

            processed_ids: set[str] = set()
            while all_message_ids - processed_ids:
                current_id = (all_message_ids - processed_ids).pop()
                processed_ids.add(current_id)

                cursor = conn.execute(
                    """
                    SELECT uid, message_id, in_reply_to, references FROM emails
                    WHERE folder = ? AND (
                        message_id = ? OR
                        in_reply_to = ? OR
                        instr(references, ?) > 0
                    )
                    """,
                    (folder, current_id, current_id, current_id),
                )

                for row in cursor.fetchall():
                    thread_uids.add(row[0])
                    if row[1]:
                        all_message_ids.add(row[1])
                    if row[2]:
                        all_message_ids.add(row[2])
                    if row[3]:
                        all_message_ids.update(row[3].split())

            return self.get_emails_by_uids(list(thread_uids), folder)

    def build_thread_index(
        self,
        folder: str = "INBOX",
        thread_data: Optional[dict[int, dict[str, Any]]] = None,
    ) -> int:
        """Build thread index from IMAP THREAD command results or local analysis.

        Args:
            folder: Folder to index
            thread_data: Optional dict from ImapClient.get_thread_structure()

        Returns:
            Number of emails updated with thread info
        """
        with self._get_connection() as conn:
            if thread_data:
                updated = 0
                for uid, info in thread_data.items():
                    conn.execute(
                        """
                        UPDATE emails SET
                            thread_root_uid = ?,
                            thread_parent_uid = ?,
                            thread_depth = ?
                        WHERE uid = ? AND folder = ?
                        """,
                        (
                            info["thread_root"],
                            info["parent_uid"],
                            info["depth"],
                            uid,
                            folder,
                        ),
                    )
                    updated += 1
                conn.commit()
                return updated

            return self._build_local_thread_index(conn, folder)

    def _build_local_thread_index(self, conn: sqlite3.Connection, folder: str) -> int:
        """Build thread index locally using References/In-Reply-To headers."""
        cursor = conn.execute(
            "SELECT uid, message_id, in_reply_to, references FROM emails WHERE folder = ?",
            (folder,),
        )
        emails = {
            row[0]: {"message_id": row[1], "in_reply_to": row[2], "references": row[3]}
            for row in cursor.fetchall()
        }

        message_id_to_uid: dict[str, int] = {}
        for uid, data in emails.items():
            if data["message_id"]:
                message_id_to_uid[data["message_id"]] = uid

        updated = 0
        for uid, data in emails.items():
            parent_uid: Optional[int] = None
            thread_root_uid = uid

            if data["in_reply_to"] and data["in_reply_to"] in message_id_to_uid:
                parent_uid = message_id_to_uid[data["in_reply_to"]]

            refs = data["references"].split() if data["references"] else []
            if refs:
                root_msg_id = refs[0]
                if root_msg_id in message_id_to_uid:
                    thread_root_uid = message_id_to_uid[root_msg_id]

            depth = len(refs)

            conn.execute(
                """
                UPDATE emails SET
                    thread_root_uid = ?,
                    thread_parent_uid = ?,
                    thread_depth = ?
                WHERE uid = ? AND folder = ?
                """,
                (thread_root_uid, parent_uid, depth, uid, folder),
            )
            updated += 1

        conn.commit()
        return updated

    def get_threads_summary(
        self, folder: str = "INBOX", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get thread summaries with most recent message and count."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT 
                    COALESCE(thread_root_uid, uid) as thread_id,
                    COUNT(*) as message_count,
                    MAX(date) as latest_date,
                    MIN(date) as earliest_date,
                    GROUP_CONCAT(DISTINCT from_addr) as participants
                FROM emails
                WHERE folder = ?
                GROUP BY COALESCE(thread_root_uid, uid)
                ORDER BY latest_date DESC
                LIMIT ?
                """,
                (folder, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
