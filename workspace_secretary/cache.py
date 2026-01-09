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
    from .imap_client import ImapClient
    from .models import Email

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_folder ON emails(folder)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_unread ON emails(is_unread)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON emails(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_from ON emails(from_addr)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_id ON emails(message_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_modseq ON emails(modseq)")
            conn.commit()
            logger.info(f"Email cache database initialized at {self.db_path}")

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
        uid_list = list(all_uids)

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

        conn.execute(
            """
            INSERT OR REPLACE INTO emails (
                uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                date, body_text, body_html, flags, is_unread, is_important, size, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

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
