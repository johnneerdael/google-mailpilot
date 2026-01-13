from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from datetime import datetime
import html

from workspace_secretary.web import database as db, templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()


def is_starred(email: dict) -> bool:
    labels = email.get("gmail_labels")
    if not labels:
        return False
    if isinstance(labels, str):
        return "\\Starred" in labels
    if isinstance(labels, list):
        return "\\Starred" in labels
    return False


def format_date(date_val) -> str:
    if not date_val:
        return ""
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return date_val[:10] if len(date_val) > 10 else date_val
    if isinstance(date_val, datetime):
        now = datetime.now(date_val.tzinfo) if date_val.tzinfo else datetime.now()
        if date_val.date() == now.date():
            return date_val.strftime("%I:%M %p")
        elif (now - date_val).days < 7:
            return date_val.strftime("%a %I:%M %p")
        else:
            return date_val.strftime("%b %d")
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


@router.get("/inbox", response_class=HTMLResponse)
async def inbox(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100),
    folder: str = Query("INBOX"),
    unread_only: bool = Query(False),
    session: Session = Depends(require_auth),
):
    offset = (page - 1) * per_page
    emails_raw = db.get_inbox_emails(folder, per_page + 1, offset, unread_only)

    has_more = len(emails_raw) > per_page
    emails_raw = emails_raw[:per_page]

    emails = [
        {
            "uid": e["uid"],
            "folder": e["folder"],
            "from_name": extract_name(e.get("from_addr", "")),
            "from_addr": e.get("from_addr", ""),
            "subject": e.get("subject", "(no subject)"),
            "preview": truncate(e.get("preview") or "", 120),
            "date": format_date(e.get("date")),
            "is_unread": e.get("is_unread", False),
            "is_starred": is_starred(e),
            "has_attachments": e.get("has_attachments", False),
        }
        for e in emails_raw
    ]

    return templates.TemplateResponse(
        "inbox.html",
        get_template_context(
            request,
            emails=emails,
            page=page,
            per_page=per_page,
            has_more=has_more,
            folder=folder,
            unread_only=unread_only,
        ),
    )


@router.get("/api/emails", response_class=HTMLResponse)
async def emails_partial(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100),
    folder: str = Query("INBOX"),
    unread_only: bool = Query(False),
    session: Session = Depends(require_auth),
):
    offset = (page - 1) * per_page
    emails_raw = db.get_inbox_emails(folder, per_page + 1, offset, unread_only)

    has_more = len(emails_raw) > per_page
    emails_raw = emails_raw[:per_page]

    emails = [
        {
            "uid": e["uid"],
            "folder": e["folder"],
            "from_name": extract_name(e.get("from_addr", "")),
            "from_addr": e.get("from_addr", ""),
            "subject": e.get("subject", "(no subject)"),
            "preview": truncate(e.get("preview") or "", 120),
            "date": format_date(e.get("date")),
            "is_unread": e.get("is_unread", False),
            "is_starred": is_starred(e),
            "has_attachments": e.get("has_attachments", False),
        }
        for e in emails_raw
    ]

    return templates.TemplateResponse(
        "partials/email_list.html",
        get_template_context(request, emails=emails, page=page, has_more=has_more),
    )


@router.get("/inbox/more", response_class=HTMLResponse)
async def inbox_more(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100),
    folder: str = Query("INBOX"),
    unread_only: bool = Query(False),
    session: Session = Depends(require_auth),
):
    offset = (page - 1) * per_page
    emails_raw = db.get_inbox_emails(folder, per_page + 1, offset, unread_only)

    has_more = len(emails_raw) > per_page
    emails_raw = emails_raw[:per_page]

    emails = [
        {
            "uid": e["uid"],
            "folder": e["folder"],
            "from_name": extract_name(e.get("from_addr", "")),
            "from_addr": e.get("from_addr", ""),
            "subject": e.get("subject", "(no subject)"),
            "preview": truncate(e.get("preview") or "", 120),
            "date": format_date(e.get("date")),
            "is_unread": e.get("is_unread", False),
            "is_starred": is_starred(e),
            "has_attachments": e.get("has_attachments", False),
        }
        for e in emails_raw
    ]

    return templates.TemplateResponse(
        "partials/inbox_more.html",
        get_template_context(
            request,
            emails=emails,
            page=page,
            has_more=has_more,
            folder=folder,
            unread_only=unread_only,
        ),
    )


@router.get("/inbox/partial", response_class=HTMLResponse)
async def inbox_widget(
    request: Request,
    limit: int = Query(5),
    unread_only: bool = Query(False),
    session: Session = Depends(require_auth),
):
    emails_raw = db.get_inbox_emails("INBOX", limit, 0, unread_only)

    emails = [
        {
            "uid": e["uid"],
            "folder": e["folder"],
            "from_name": extract_name(e.get("from_addr", "")),
            "subject": e.get("subject", "(no subject)"),
            "preview": truncate(e.get("preview") or "", 80),
            "date": format_date(e.get("date")),
            "is_unread": e.get("is_unread", False),
        }
        for e in emails_raw
    ]

    return templates.TemplateResponse(
        "partials/email_widget.html",
        get_template_context(request, emails=emails),
    )
