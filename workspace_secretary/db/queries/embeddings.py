"""Embedding and semantic search query functions."""

from __future__ import annotations

from typing import Any, cast

from psycopg.rows import dict_row

from workspace_secretary.db.types import DatabaseInterface


def upsert_embedding(
    db: DatabaseInterface,
    uid: int,
    folder: str,
    embedding: list[float],
    model: str,
    content_hash: str,
) -> None:
    """Insert or update email embedding."""
    with db.connection() as conn:
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


def semantic_search(
    db: DatabaseInterface,
    query_embedding: list[float],
    folder: str,
    limit: int,
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Semantic search using inner product on normalized vectors."""
    vtype = cast(Any, db)._vector_type
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT e.uid, e.folder, e.from_addr, e.subject, 
                       LEFT(e.body_text, 200) as preview, e.date, e.is_unread,
                       -(emb.embedding <#> %s::{vtype}) as similarity
                FROM email_embeddings emb
                JOIN emails e ON e.uid = emb.email_uid AND e.folder = emb.email_folder
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


def semantic_search_advanced(
    db: DatabaseInterface,
    query_embedding: list[float],
    folder: str,
    limit: int,
    filters: dict[str, Any],
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Semantic search with advanced metadata filters."""
    vtype = cast(Any, db)._vector_type
    conditions = ["e.folder = %s", f"-(emb.embedding <#> %s::{vtype}) > %s"]
    params: list[Any] = [folder, query_embedding, threshold]

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
        JOIN emails e ON e.uid = emb.email_uid AND e.folder = emb.email_folder
        WHERE {" AND ".join(conditions)}
        ORDER BY emb.embedding <#> %s::{vtype} LIMIT %s
    """

    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def find_related_emails(
    db: DatabaseInterface,
    uid: int,
    folder: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find emails similar to a reference email."""
    vtype = cast(Any, db)._vector_type
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT embedding FROM email_embeddings WHERE email_uid = %s AND email_folder = %s",
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
                JOIN emails e ON e.uid = emb.email_uid AND e.folder = emb.email_folder
                WHERE NOT (e.uid = %s AND e.folder = %s)
                  AND -(emb.embedding <#> %s::{vtype}) > 0.6
                ORDER BY emb.embedding <#> %s::{vtype} LIMIT %s
            """,
                (embedding, uid, folder, embedding, embedding, limit),
            )
            return cur.fetchall()


def has_embeddings(db: DatabaseInterface) -> bool:
    """Check if any embeddings exist in database."""
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM email_embeddings LIMIT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


def count_emails_needing_embedding(db: DatabaseInterface, folder: str) -> int:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM emails e
                LEFT JOIN email_embeddings emb 
                    ON e.uid = emb.email_uid AND e.folder = emb.email_folder
                WHERE e.folder = %s AND emb.email_uid IS NULL
                """,
                (folder,),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def get_emails_needing_embedding(
    db: DatabaseInterface,
    folder: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT e.uid, e.folder, e.subject, e.body_text, e.content_hash
                FROM emails e
                LEFT JOIN email_embeddings emb 
                    ON e.uid = emb.email_uid AND e.folder = emb.email_folder
                WHERE e.folder = %s AND emb.email_uid IS NULL
                ORDER BY e.date DESC
                LIMIT %s
                """,
                (folder, limit),
            )
            return cur.fetchall()
