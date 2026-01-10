from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import html
import os
import httpx
import json

from workspace_secretary.web import database as db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

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


async def get_embedding(text: str) -> Optional[list[float]]:
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
):
    supports_semantic = db.has_embeddings()
    folders = db.get_folders()

    # Build filters dict
    filters = {
        "from_addr": from_addr,
        "date_from": date_from,
        "date_to": date_to,
        "has_attachments": has_attachments,
        "is_unread": is_unread,
    }

    # Check if any filters are active
    has_filters = any(
        [
            from_addr,
            date_from,
            date_to,
            has_attachments is not None,
            is_unread is not None,
        ]
    )

    if not q.strip() and not has_filters:
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "query": "",
                "mode": mode,
                "results": [],
                "folder": folder,
                "folders": folders,
                "supports_semantic": supports_semantic,
                "filters": filters,
                "saved_searches": _saved_searches,
            },
        )

    results_raw = []
    if mode == "semantic" and supports_semantic and q.strip():
        embedding = await get_embedding(q)
        if embedding:
            results_raw = db.semantic_search_advanced(embedding, folder, limit, filters)
        else:
            results_raw = db.search_emails_advanced(q, folder, limit, filters)
    else:
        results_raw = db.search_emails_advanced(q, folder, limit, filters)

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
        {
            "request": request,
            "query": q,
            "mode": mode,
            "results": results,
            "folder": folder,
            "folders": folders,
            "supports_semantic": supports_semantic,
            "filters": filters,
            "saved_searches": _saved_searches,
        },
    )


@router.post("/search/save", response_class=HTMLResponse)
async def save_search(request: Request):
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
        {"request": request, "saved_searches": _saved_searches},
    )


@router.delete("/search/saved/{search_id}", response_class=HTMLResponse)
async def delete_saved_search(request: Request, search_id: int):
    """Delete a saved search."""
    global _saved_searches
    _saved_searches = [s for s in _saved_searches if s["id"] != search_id]
    return templates.TemplateResponse(
        "partials/saved_searches.html",
        {"request": request, "saved_searches": _saved_searches},
    )


@router.get("/search/suggestions", response_class=HTMLResponse)
async def search_suggestions(request: Request, q: str = Query("")):
    """Get search suggestions based on partial query."""
    if len(q) < 2:
        return HTMLResponse("")

    suggestions = db.get_search_suggestions(q)
    if not suggestions:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "partials/search_suggestions.html",
        {"request": request, "suggestions": suggestions},
    )
