"""
Direct PostgreSQL connection for web UI - read-only access.
"""

from typing import Optional
from contextlib import contextmanager
import logging
import psycopg_pool
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

_pool = None
_vector_type = None  # Cached vector type (vector or halfvec)


def get_pool():
    global _pool
    if _pool is None:
        from workspace_secretary.config import load_config

        config = load_config()
        db = config.database.postgres

        conninfo = f"host={db.host} port={db.port} dbname={db.database} user={db.user} password={db.password}"
        _pool = psycopg_pool.ConnectionPool(conninfo, min_size=1, max_size=5)
        logger.info("Web UI database pool initialized")
    return _pool


def get_vector_type() -> str:
    """Get the vector type based on embedding dimensions config.

    Returns 'halfvec' for dimensions > 2000 (HNSW index limit), otherwise 'vector'.
    """
    global _vector_type
    if _vector_type is None:
        from workspace_secretary.config import load_config

        config = load_config()
        dims = (
            config.database.embeddings.dimensions
            if config.database.embeddings
            else 1536
        )
        _vector_type = "halfvec" if dims > 2000 else "vector"
    return _vector_type


@contextmanager
def get_conn():
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def get_inbox_emails(
    folder: str, limit: int, offset: int, unread_only: bool = False
) -> list[dict]:
    sql = """
        SELECT uid, folder, from_addr, subject, 
               LEFT(body_text, 200) as preview, date, is_unread, has_attachments,
               gmail_labels
        FROM emails 
        WHERE folder = %s {unread_filter}
        ORDER BY date DESC 
        LIMIT %s OFFSET %s
    """
    unread_filter = "AND is_unread = true" if unread_only else ""
    sql = sql.format(unread_filter=unread_filter)

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (folder, limit, offset))
            return cur.fetchall()


def get_email(uid: int, folder: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM emails WHERE uid = %s AND folder = %s", (uid, folder)
            )
            return cur.fetchone()


def get_neighbor_uids(
    folder: str, uid: int, unread_only: bool = False
) -> dict[str, Optional[int]]:
    """Get the UIDs of the next and previous emails in the current list context."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get current email's date
            cur.execute(
                "SELECT date FROM emails WHERE uid = %s AND folder = %s", (uid, folder)
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


def get_thread(uid: int, folder: str) -> list[dict]:
    with get_conn() as conn:
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
                    "SELECT * FROM emails WHERE uid = %s AND folder = %s", (uid, folder)
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


def search_emails(query: str, folder: str, limit: int) -> list[dict]:
    with get_conn() as conn:
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


def semantic_search(
    query_embedding: list[float], folder: str, limit: int, threshold: float = 0.5
) -> list[dict]:
    """Semantic search using inner product on normalized vectors."""
    vtype = get_vector_type()
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT e.uid, e.folder, e.from_addr, e.subject, 
                       LEFT(e.body_text, 200) as preview, e.date, e.is_unread,
                       -(emb.embedding <#> %s::{vtype}) as similarity
                FROM email_embeddings emb
                JOIN emails e ON e.uid = emb.uid AND e.folder = emb.folder
                WHERE e.folder = %s AND -(emb.embedding <#> %s::{vtype}) > %s
                ORDER BY emb.embedding <#> %s::{vtype} LIMIT %s
            """,
                (
                    query_embedding,
                    folder,
                    query_embedding,
                    threshold,
                    query_embedding,
                    limit,
                ),
            )
            return cur.fetchall()


def has_embeddings() -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM email_embeddings LIMIT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


def get_folders() -> list[str]:
    """Get list of all folders."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT folder FROM emails ORDER BY folder")
            return [row[0] for row in cur.fetchall()]


def search_emails_advanced(
    query: str, folder: str, limit: int, filters: dict
) -> list[dict]:
    """Search emails with advanced filters."""
    conditions = ["folder = %s"]
    params: list = [folder]

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

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def semantic_search_advanced(
    query_embedding: list[float],
    folder: str,
    limit: int,
    filters: dict,
    threshold: float = 0.5,
) -> list[dict]:
    """Semantic search with advanced metadata filters using inner product."""
    vtype = get_vector_type()
    conditions = ["e.folder = %s", f"-(emb.embedding <#> %s::{vtype}) > %s"]
    params: list = [folder, query_embedding, threshold]

    if filters.get("from_addr"):
        conditions.append("e.from_addr ILIKE %s")
        params.append(f"%{filters['from_addr']}%")

    if filters.get("date_from"):
        conditions.append("e.date >= %s")
        params.append(filters["date_from"])

    if filters.get("date_to"):
        conditions.append("e.date <= %s")
        params.append(filters["date_to"])

    if filters.get("has_attachments") is not None:
        conditions.append("e.has_attachments = %s")
        params.append(filters["has_attachments"])

    if filters.get("is_unread") is not None:
        conditions.append("e.is_unread = %s")
        params.append(filters["is_unread"])

    if filters.get("to_addr"):
        conditions.append("e.to_addr ILIKE %s")
        params.append(f"%{filters['to_addr']}%")

    if filters.get("subject_contains"):
        conditions.append("e.subject ILIKE %s")
        params.append(f"%{filters['subject_contains']}%")

    if filters.get("is_starred") is not None:
        if filters["is_starred"]:
            conditions.append("e.gmail_labels ? '\\\\Starred'")

    if filters.get("attachment_filename"):
        conditions.append("e.attachment_filenames::text ILIKE %s")
        params.append(f"%{filters['attachment_filename']}%")

    params.extend([query_embedding, query_embedding, limit])

    sql = f"""
        SELECT e.uid, e.folder, e.from_addr, e.subject, 
               LEFT(e.body_text, 200) as preview, e.date, e.is_unread, e.has_attachments,
               -(emb.embedding <#> %s::{vtype}) as similarity
        FROM email_embeddings emb
        JOIN emails e ON e.uid = emb.uid AND e.folder = emb.folder
        WHERE {" AND ".join(conditions)}
        ORDER BY emb.embedding <#> %s::{vtype} LIMIT %s
    """

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def get_search_suggestions(query: str, limit: int = 5) -> list[dict]:
    """Get search suggestions based on partial query (senders and subjects)."""
    suggestions = []
    with get_conn() as conn:
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
                SELECT DISTINCT subject
                FROM emails
                WHERE subject ILIKE %s
                ORDER BY date DESC LIMIT %s
                """,
                (f"%{query}%", limit),
            )
            for row in cur.fetchall():
                if row["subject"]:
                    suggestions.append({"type": "subject", "value": row["subject"]})

    return suggestions[:limit]


def find_related_emails(uid: int, folder: str, limit: int = 5) -> list[dict]:
    vtype = get_vector_type()
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT embedding FROM email_embeddings WHERE uid = %s AND folder = %s",
                (uid, folder),
            )
            row = cur.fetchone()
            if not row:
                return []

            embedding = row["embedding"]
            cur.execute(
                f"""
                SELECT e.uid, e.folder, e.from_addr, e.subject, 
                       LEFT(e.body_text, 150) as preview, e.date,
                       -(emb.embedding <#> %s::{vtype}) as similarity
                FROM email_embeddings emb
                JOIN emails e ON e.uid = emb.uid AND e.folder = emb.folder
                WHERE NOT (e.uid = %s AND e.folder = %s)
                  AND -(emb.embedding <#> %s::{vtype}) > 0.6
                ORDER BY emb.embedding <#> %s::{vtype} LIMIT %s
            """,
                (embedding, uid, folder, embedding, embedding, limit),
            )
            return cur.fetchall()


def get_new_priority_emails(since, limit: int = 10) -> list[dict]:
    """Get new priority emails since a given datetime."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Try to get priority emails - fall back to unread from recent if no priority system
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
