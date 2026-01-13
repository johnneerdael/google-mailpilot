from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime, timedelta
import html
import os
import httpx
import json

from workspace_secretary.web import database as db, templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()

# In-memory saved searches (in production, store in DB or config)
_saved_searches: list[dict] = []


def format_date(date_val) -> str:
    if not date_val:
        return ""
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return date_val[:10] if len(date_val) > 10 else date_val
    if isinstance(date_val, datetime):
        return date_val.strftime("%b %d, %Y")
    return str(date_val)


def truncate(text: str, length: int = 100) -> str:
    if not text:
        return ""
    text = html.escape(text.strip())
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "..."


def extract_name(addr: str) -> str:
    if not addr:
        return ""
    if "<" in addr:
        return addr.split("<")[0].strip().strip('"')
    return addr.split("@")[0]


def parse_search_operators(query: str) -> tuple[str, dict]:
    """
    Parse Gmail-style search operators from query string.

    Supported operators:
    - from:email@example.com
    - to:email@example.com
    - subject:keyword
    - has:attachment
    - attachment:filename.pdf
    - is:unread
    - is:read
    - is:starred

    Returns: (plain_query, filters_dict)
    """
    import re

    filters = {}
    remaining_parts = []

    operators = {
        "from": "from_addr",
        "to": "to_addr",
        "subject": "subject_contains",
        "has": "has_type",
        "is": "is_state",
        "attachment": "attachment_filename",
    }

    pattern = r"(\w+):([^\s]+)"

    for match in re.finditer(pattern, query):
        operator = match.group(1).lower()
        value = match.group(2)

        if operator == "from":
            filters["from_addr"] = value
        elif operator == "to":
            filters["to_addr"] = value
        elif operator == "subject":
            filters["subject_contains"] = value
        elif operator == "attachment":
            filters["attachment_filename"] = value
        elif operator == "has":
            if value == "attachment":
                filters["has_attachments"] = True
        elif operator == "is":
            if value == "unread":
                filters["is_unread"] = True
            elif value == "read":
                filters["is_unread"] = False
            elif value == "starred":
                filters["is_starred"] = True

    plain_query = re.sub(pattern, "", query).strip()
    plain_query = re.sub(r"\s+", " ", plain_query)

    return plain_query, filters


async def get_embedding(text: str) -> Optional[list[float]]:
    provider = os.environ.get("EMBEDDINGS_PROVIDER", "openai_compat")

    if provider == "cohere":
        api_key = os.environ.get("EMBEDDINGS_API_KEY") or os.environ.get(
            "COHERE_API_KEY"
        )
        model = os.environ.get("EMBEDDINGS_MODEL", "embed-v4.0")
        if not api_key:
            return None
        try:
            import cohere

            client = cohere.ClientV2(api_key=api_key)
            response = client.embed(
                texts=[text],
                model=model,
                input_type="search_query",
                embedding_types=["float"],
            )
            return (
                list(response.embeddings.float_[0])
                if response.embeddings.float_
                else None
            )
        except Exception:
            return None

    api_base = os.environ.get("EMBEDDINGS_API_BASE")
    api_key = os.environ.get("EMBEDDINGS_API_KEY", "")
    model = os.environ.get("EMBEDDINGS_MODEL", "text-embedding-3-small")

    if not api_base:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{api_base}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": text},
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
    except Exception:
        return None


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(""),
    mode: str = Query("keyword"),
    folder: str = Query("INBOX"),
    limit: int = Query(50, ge=1, le=100),
    # Advanced filters
    from_addr: str = Query("", alias="from"),
    date_from: str = Query(""),
    date_to: str = Query(""),
    has_attachments: Optional[bool] = Query(None),
    is_unread: Optional[bool] = Query(None),
    session: Session = Depends(require_auth),
):
    supports_semantic = db.has_embeddings()
    folders = db.get_folders()

    # Parse search operators from query string
    parsed_query, parsed_filters = parse_search_operators(q)

    # Build filters dict from URL params
    filters = {
        "from_addr": from_addr,
        "date_from": date_from,
        "date_to": date_to,
        "has_attachments": has_attachments,
        "is_unread": is_unread,
    }

    # Merge parsed operators (parsed_filters take precedence)
    filters.update({k: v for k, v in parsed_filters.items() if v is not None})

    # Check if any filters are active
    has_filters = any(
        [
            filters.get("from_addr"),
            filters.get("to_addr"),
            filters.get("subject_contains"),
            date_from,
            date_to,
            filters.get("has_attachments") is not None,
            filters.get("is_unread") is not None,
            filters.get("is_starred") is not None,
        ]
    )

    if not parsed_query.strip() and not has_filters:
        return templates.TemplateResponse(
            "search.html",
            get_template_context(
                request,
                query=q,
                parsed_query=parsed_query,
                mode=mode,
                results=[],
                folder=folder,
                folders=folders,
                supports_semantic=supports_semantic,
                filters=filters,
                saved_searches=_saved_searches,
            ),
        )

    results_raw = []
    if mode == "semantic" and supports_semantic and parsed_query.strip():
        embedding = await get_embedding(parsed_query)
        if embedding:
            results_raw = db.semantic_search_advanced(embedding, folder, limit, filters)
        else:
            results_raw = db.search_emails_advanced(
                parsed_query, folder, limit, filters
            )
    else:
        results_raw = db.search_emails_advanced(parsed_query, folder, limit, filters)

    results = [
        {
            "uid": e["uid"],
            "folder": e.get("folder", folder),
            "from_name": extract_name(e.get("from_addr", "")),
            "from_addr": e.get("from_addr", ""),
            "subject": e.get("subject", "(no subject)"),
            "preview": truncate(e.get("preview") or "", 150),
            "date": format_date(e.get("date")),
            "similarity": e.get("similarity"),
            "is_unread": e.get("is_unread", False),
            "has_attachments": e.get("has_attachments", False),
        }
        for e in results_raw
    ]

    return templates.TemplateResponse(
        "search.html",
        get_template_context(
            request,
            query=q,
            parsed_query=parsed_query,
            mode=mode,
            results=results,
            folder=folder,
            folders=folders,
            supports_semantic=supports_semantic,
            filters=filters,
            saved_searches=_saved_searches,
            active_operators=parsed_filters,
        ),
    )


@router.post("/search/save", response_class=HTMLResponse)
async def save_search(request: Request, session: Session = Depends(require_auth)):
    """Save current search as a quick filter."""
    form = await request.form()
    name_val = form.get("name", "")
    query_val = form.get("query", "")
    name = str(name_val).strip() if name_val else ""
    query = str(query_val).strip() if query_val else ""
    mode = form.get("mode", "keyword")
    folder = form.get("folder", "INBOX")
    from_addr = form.get("from", "")
    date_from = form.get("date_from", "")
    date_to = form.get("date_to", "")
    has_attachments = form.get("has_attachments")
    is_unread = form.get("is_unread")

    if name:
        saved = {
            "id": len(_saved_searches) + 1,
            "name": name,
            "query": query,
            "mode": mode,
            "folder": folder,
            "from_addr": from_addr,
            "date_from": date_from,
            "date_to": date_to,
            "has_attachments": has_attachments == "true" if has_attachments else None,
            "is_unread": is_unread == "true" if is_unread else None,
        }
        _saved_searches.append(saved)

    # Return updated saved searches list
    return templates.TemplateResponse(
        "partials/saved_searches.html",
        get_template_context(request, saved_searches=_saved_searches),
    )


@router.delete("/search/saved/{search_id}", response_class=HTMLResponse)
async def delete_saved_search(
    request: Request, search_id: int, session: Session = Depends(require_auth)
):
    """Delete a saved search."""
    global _saved_searches
    _saved_searches = [s for s in _saved_searches if s["id"] != search_id]
    return templates.TemplateResponse(
        "partials/saved_searches.html",
        get_template_context(request, saved_searches=_saved_searches),
    )


@router.get("/search/suggestions", response_class=HTMLResponse)
async def search_suggestions(
    request: Request, q: str = Query(""), session: Session = Depends(require_auth)
):
    """Get search suggestions based on partial query."""
    if len(q) < 2:
        return HTMLResponse("")

    suggestions = db.get_search_suggestions(q)
    if not suggestions:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "partials/search_suggestions.html",
        get_template_context(request, suggestions=suggestions),
    )
