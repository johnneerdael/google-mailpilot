"""Email query functions - extracted from engine and web database layers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from psycopg.rows import dict_row

from workspace_secretary.db.types import DatabaseInterface


# ============================================================================
# Core Email CRUD Operations (from engine/database.py)
# ============================================================================


def upsert_email(
    db: DatabaseInterface,
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
    """Insert or update email with full metadata."""
    content = f"{subject or ''}{body_text}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

    gmail_labels_json = json.dumps(gmail_labels) if gmail_labels else None
    attachment_filenames_json = (
        json.dumps(attachment_filenames) if attachment_filenames else None
    )
    suspicious_sender_signals_json = (
        json.dumps(suspicious_sender_signals) if suspicious_sender_signals else None
    )

    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO emails (
                    uid, folder, message_id, subject, from_addr, to_addr, cc_addr,
                    bcc_addr, date, internal_date, body_text, body_html, flags,
                    is_unread, is_important, size, modseq, synced_at, in_reply_to,
                    references_header, content_hash, gmail_thread_id, gmail_msgid,
                    gmail_labels, has_attachments, attachment_filenames,
                    auth_results_raw, spf, dkim, dmarc, is_suspicious_sender, suspicious_sender_signals,
                    security_score, warning_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    suspicious_sender_signals = EXCLUDED.suspicious_sender_signals,
                    security_score = EXCLUDED.security_score,
                    warning_type = EXCLUDED.warning_type
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
                    security_score,
                    warning_type,
                ),
            )
            conn.commit()


def update_email_flags(
    db: DatabaseInterface,
    uid: int,
    folder: str,
    flags: str,
    is_unread: bool,
    modseq: int,
    gmail_labels: Optional[list[str]] = None,
) -> None:
    """Update email flags and Gmail labels."""
    gmail_labels_json = json.dumps(gmail_labels) if gmail_labels else None

    with db.connection() as conn:
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


def get_email(
    db: DatabaseInterface,
    uid: int,
    folder: str,
) -> Optional[dict[str, Any]]:
    """Get email by UID and folder."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM emails WHERE uid = %s AND folder = %s",
                (uid, folder),
            )
            return cur.fetchone()


def get_emails_by_uids(
    db: DatabaseInterface,
    uids: list[int],
    folder: str,
) -> list[dict[str, Any]]:
    """Get multiple emails by UIDs."""
    if not uids:
        return []
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM emails WHERE folder = %s AND uid = ANY(%s) ORDER BY date DESC",
                (folder, uids),
            )
            return cur.fetchall()


def search_emails(
    db: DatabaseInterface,
    folder: str = "INBOX",
    is_unread: Optional[bool] = None,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
    subject_contains: Optional[str] = None,
    body_contains: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Search emails with basic filters."""
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

    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def delete_email(db: DatabaseInterface, uid: int, folder: str) -> None:
    """Delete email by UID and folder."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM emails WHERE uid = %s AND folder = %s",
                (uid, folder),
            )
            conn.commit()


def mark_email_read(
    db: DatabaseInterface,
    uid: int,
    folder: str,
    is_read: bool,
) -> None:
    """Mark email as read or unread."""
    with db.connection() as conn:
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


def get_synced_uids(db: DatabaseInterface, folder: str) -> list[int]:
    """Get all synced UIDs for a folder."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT uid FROM emails WHERE folder = %s", (folder,))
            rows = cur.fetchall()
            return [int(row[0]) for row in rows]


def count_emails(db: DatabaseInterface, folder: str) -> int:
    """Count emails in folder."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM emails WHERE folder = %s", (folder,))
            row = cur.fetchone()
            return int(row[0]) if row else 0


# ============================================================================
# Folder State Management (CONDSTORE)
# ============================================================================


def get_folder_state(
    db: DatabaseInterface,
    folder: str,
) -> Optional[dict[str, Any]]:
    """Get CONDSTORE state for folder."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT uidvalidity, uidnext, highestmodseq, last_sync FROM folder_state WHERE folder = %s",
                (folder,),
            )
            return cur.fetchone()


def save_folder_state(
    db: DatabaseInterface,
    folder: str,
    uidvalidity: int,
    uidnext: int,
    highestmodseq: int = 0,
) -> None:
    """Save CONDSTORE state for folder."""
    with db.connection() as conn:
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


def clear_folder(db: DatabaseInterface, folder: str) -> int:
    """Clear all emails from folder, return count deleted."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM emails WHERE folder = %s", (folder,))
            deleted = cur.rowcount
            conn.commit()
            return deleted


def get_folders(db: DatabaseInterface) -> list[str]:
    """Get list of all distinct folders."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT folder FROM emails ORDER BY folder")
            return [row[0] for row in cur.fetchall()]


def get_synced_folders(db: DatabaseInterface) -> list[dict[str, Any]]:
    """Get all folders with sync state metadata."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT folder, uidvalidity, uidnext, highestmodseq, last_sync
                FROM folder_state
                ORDER BY folder
                """
            )
            return cur.fetchall()


# ============================================================================
# Sync Error Logging
# ============================================================================


def log_sync_error(
    db: DatabaseInterface,
    error_type: str,
    error_message: str,
    folder: Optional[str] = None,
    email_uid: Optional[int] = None,
) -> None:
    """Log sync error."""
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_errors (folder, email_uid, error_type, error_message)
                VALUES (%s, %s, %s, %s)
                """,
                (folder, email_uid, error_type, error_message),
            )
            conn.commit()


# ============================================================================
# Web UI Queries (from web/database.py)
# ============================================================================


def get_inbox_emails(
    db: DatabaseInterface,
    folder: str,
    limit: int,
    offset: int,
    unread_only: bool = False,
    label: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get inbox emails with preview for list view.

    Args:
        db: Database interface
        folder: IMAP folder name (ignored if label is specified)
        limit: Max emails to return
        offset: Pagination offset
        unread_only: Only return unread emails
        label: Gmail label to filter by (e.g., "Secretary/Priority")
    """
    # Build filter conditions
    filters = []
    params: list[Any] = []

    if label:
        # Filter by Gmail label (stored as JSON array)
        filters.append("gmail_labels::jsonb ? %s")
        params.append(label)
    else:
        # Filter by folder
        filters.append("folder = %s")
        params.append(folder)

    if unread_only:
        filters.append("is_unread = true")

    where_clause = " AND ".join(filters)

    sql = f"""
        SELECT uid, folder, from_addr, to_addr, cc_addr, subject, 
               LEFT(body_text, 200) as preview, date, is_unread, has_attachments,
               gmail_labels
        FROM emails 
        WHERE {where_clause}
        ORDER BY date DESC 
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def get_neighbor_uids(
    db: DatabaseInterface,
    folder: str,
    uid: int,
    unread_only: bool = False,
) -> dict[str, Optional[int]]:
    """Get UIDs of next and previous emails for navigation."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get current email's date
            cur.execute(
                "SELECT date FROM emails WHERE uid = %s AND folder = %s",
                (uid, folder),
            )
            current = cur.fetchone()
            if not current:
                return {"next": None, "prev": None}

            current_date = current["date"]
            unread_filter = "AND is_unread = true" if unread_only else ""

            # Next (Newer) - ORDER BY date ASC
            sql_next = f"""
                SELECT uid FROM emails 
                WHERE folder = %s {unread_filter}
                AND (date > %s OR (date = %s AND uid > %s))
                ORDER BY date ASC, uid ASC LIMIT 1
            """
            cur.execute(sql_next, (folder, current_date, current_date, uid))
            next_row = cur.fetchone()

            # Previous (Older) - ORDER BY date DESC
            sql_prev = f"""
                SELECT uid FROM emails 
                WHERE folder = %s {unread_filter}
                AND (date < %s OR (date = %s AND uid < %s))
                ORDER BY date DESC, uid DESC LIMIT 1
            """
            cur.execute(sql_prev, (folder, current_date, current_date, uid))
            prev_row = cur.fetchone()

            return {
                "next": next_row["uid"] if next_row else None,
                "prev": prev_row["uid"] if prev_row else None,
            }


def get_thread(
    db: DatabaseInterface,
    uid: int,
    folder: str,
) -> list[dict[str, Any]]:
    """Get email thread by reconstructing from message-id/references."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT message_id, in_reply_to, references_header FROM emails WHERE uid = %s AND folder = %s",
                (uid, folder),
            )
            row = cur.fetchone()
            if not row:
                return []

            message_id = row["message_id"]
            in_reply_to = row["in_reply_to"] or ""
            references = row["references_header"] or ""

            related_ids = set()
            if message_id:
                related_ids.add(message_id)
            for ref in (in_reply_to + " " + references).split():
                if ref:
                    related_ids.add(ref)

            if not related_ids:
                cur.execute(
                    "SELECT * FROM emails WHERE uid = %s AND folder = %s",
                    (uid, folder),
                )
                single = cur.fetchone()
                return [single] if single else []

            cur.execute(
                """
                SELECT * FROM emails 
                WHERE message_id = ANY(%s) OR in_reply_to = ANY(%s)
                ORDER BY date ASC
            """,
                (list(related_ids), list(related_ids)),
            )
            return cur.fetchall()


def search_emails_fts(
    db: DatabaseInterface,
    query: str,
    folder: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Search emails using PostgreSQL full-text search."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT uid, folder, from_addr, subject, 
                       LEFT(body_text, 200) as preview, date, is_unread
                FROM emails 
                WHERE folder = %s AND (
                    to_tsvector('english', COALESCE(subject, '') || ' ' || COALESCE(body_text, '')) 
                    @@ plainto_tsquery('english', %s)
                )
                ORDER BY date DESC LIMIT %s
            """,
                (folder, query, limit),
            )
            return cur.fetchall()


def search_emails_advanced(
    db: DatabaseInterface,
    query: str,
    folder: str,
    limit: int,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Search emails with advanced metadata filters."""
    conditions = ["folder = %s"]
    params: list[Any] = [folder]

    if query.strip():
        conditions.append(
            """(
                to_tsvector('english', COALESCE(subject, '') || ' ' || COALESCE(body_text, '')) 
                @@ plainto_tsquery('english', %s)
            )"""
        )
        params.append(query)

    if filters.get("from_addr"):
        conditions.append("from_addr ILIKE %s")
        params.append(f"%{filters['from_addr']}%")

    if filters.get("date_from"):
        conditions.append("date >= %s")
        params.append(filters["date_from"])

    if filters.get("date_to"):
        conditions.append("date <= %s")
        params.append(filters["date_to"])

    if filters.get("has_attachments") is not None:
        conditions.append("has_attachments = %s")
        params.append(filters["has_attachments"])

    if filters.get("is_unread") is not None:
        conditions.append("is_unread = %s")
        params.append(filters["is_unread"])

    if filters.get("to_addr"):
        conditions.append("to_addr ILIKE %s")
        params.append(f"%{filters['to_addr']}%")

    if filters.get("subject_contains"):
        conditions.append("subject ILIKE %s")
        params.append(f"%{filters['subject_contains']}%")

    if filters.get("is_starred") is not None:
        if filters["is_starred"]:
            conditions.append("gmail_labels ? '\\\\Starred'")

    if filters.get("attachment_filename"):
        conditions.append("attachment_filenames::text ILIKE %s")
        params.append(f"%{filters['attachment_filename']}%")

    params.append(limit)

    sql = f"""
        SELECT uid, folder, from_addr, subject, 
               LEFT(body_text, 200) as preview, date, is_unread, has_attachments
        FROM emails 
        WHERE {" AND ".join(conditions)}
        ORDER BY date DESC LIMIT %s
    """

    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def get_search_suggestions(
    db: DatabaseInterface,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get search suggestions for autocomplete (senders and subjects)."""
    suggestions: list[dict[str, Any]] = []
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Suggest senders
            cur.execute(
                """
                SELECT DISTINCT from_addr, COUNT(*) as cnt
                FROM emails
                WHERE from_addr ILIKE %s
                GROUP BY from_addr
                ORDER BY cnt DESC LIMIT %s
                """,
                (f"%{query}%", limit),
            )
            for row in cur.fetchall():
                suggestions.append({"type": "sender", "value": row["from_addr"]})

            # Suggest subjects
            cur.execute(
                """
                SELECT subject
                FROM emails
                WHERE subject ILIKE %s
                GROUP BY subject
                ORDER BY MAX(date) DESC LIMIT %s
                """,
                (f"%{query}%", limit),
            )
            for row in cur.fetchall():
                if row["subject"]:
                    suggestions.append({"type": "subject", "value": row["subject"]})

    return suggestions[:limit]


def get_new_priority_emails(
    db: DatabaseInterface,
    since,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get new priority emails since a given datetime."""
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    SELECT uid, folder, from_addr, subject, 
                           LEFT(body_text, 200) as preview, date
                    FROM emails
                    WHERE date > %s
                      AND is_unread = true
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (since, limit),
                )
                return cur.fetchall()
            except Exception:
                return []
