from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
import html
import re

from workspace_secretary.web import database as db
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def format_datetime(date_val) -> str:
    if not date_val:
        return ""
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return date_val
    if isinstance(date_val, datetime):
        return date_val.strftime("%b %d, %Y at %I:%M %p")
    return str(date_val)


def extract_name(addr: str) -> str:
    if not addr:
        return ""
    if "<" in addr:
        return addr.split("<")[0].strip().strip('"')
    return addr.split("@")[0]


def sanitize_html(html_content: str) -> str:
    if not html_content:
        return ""
    html_content = re.sub(
        r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    html_content = re.sub(
        r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    html_content = re.sub(
        r"\son\w+\s*=", " data-removed=", html_content, flags=re.IGNORECASE
    )
    return html_content


def text_to_html(text: str) -> str:
    if not text:
        return ""
    text = html.escape(text)
    text = text.replace("\n\n", "</p><p>")
    text = text.replace("\n", "<br>")
    return f"<p>{text}</p>"


def detect_calendar_invite(email: dict) -> dict | None:
    content_type = email.get("content_type", "")
    subject = email.get("subject", "").lower()
    body_text = email.get("body_text", "").lower()

    is_invite = (
        "calendar" in content_type
        or "text/calendar" in content_type
        or "invitation" in subject
        or "invite" in subject
        or "meeting request" in subject
        or "vcalendar" in body_text
        or "begin:vevent" in body_text
    )

    if not is_invite:
        return None

    event_id = email.get("calendar_event_id")
    if not event_id:
        message_id = email.get("message_id", "")
        event_id = (
            message_id.replace("<", "").replace(">", "").split("@")[0]
            if message_id
            else None
        )

    return {
        "event_id": event_id,
        "subject": email.get("subject", "Meeting"),
    }


@router.get("/thread/{folder}/{uid}", response_class=HTMLResponse)
async def thread_view(
    request: Request, folder: str, uid: int, session: Session = Depends(require_auth)
):
    email = db.get_email(uid, folder)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    thread_emails = db.get_thread(uid, folder)
    if not thread_emails:
        thread_emails = [email]

    messages = []
    calendar_invite = None

    for e in thread_emails:
        body_html = e.get("body_html", "")
        body_text = e.get("body_text", "")
        content = sanitize_html(body_html) if body_html else text_to_html(body_text)

        if not calendar_invite:
            calendar_invite = detect_calendar_invite(e)

        messages.append(
            {
                "uid": e["uid"],
                "folder": e["folder"],
                "from_name": extract_name(e.get("from_addr", "")),
                "from_addr": e.get("from_addr", ""),
                "to_addr": e.get("to_addr", ""),
                "cc_addr": e.get("cc_addr", ""),
                "subject": e.get("subject", "(no subject)"),
                "date": format_datetime(e.get("date")),
                "content": content,
                "is_unread": e.get("is_unread", False),
                "has_attachments": e.get("has_attachments", False),
                "attachment_filenames": e.get("attachment_filenames", []),
            }
        )

    return templates.TemplateResponse(
        "thread.html",
        {
            "request": request,
            "subject": email.get("subject", "(no subject)"),
            "messages": messages,
            "folder": folder,
            "uid": uid,
            "calendar_invite": calendar_invite,
        },
    )
