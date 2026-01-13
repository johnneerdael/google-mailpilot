from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from datetime import datetime
import html
import re
import httpx

from workspace_secretary.web import database as db, templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session
from workspace_secretary.web.engine_client import get_engine_url

router = APIRouter()


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


def sanitize_html(html_content: str, block_images: bool = True) -> str:
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

    if block_images:
        html_content = re.sub(
            r'<img([^>]*)\ssrc=["\']([^"\']*)["\']',
            r'<img\1 data-src="\2" src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'100\' height=\'100\'%3E%3Crect width=\'100\' height=\'100\' fill=\'%23374151\'/%3E%3Ctext x=\'50%25\' y=\'50%25\' text-anchor=\'middle\' dy=\'.3em\' fill=\'%23d1d5db\' font-size=\'12\'%3EImage%3C/text%3E%3C/svg%3E"',
            html_content,
            flags=re.IGNORECASE,
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


def split_quoted_text(content: str) -> tuple[str, str]:
    if not content:
        return "", ""

    patterns = [
        r"(?i)(<br\s*/?>|<div>| )*On\s+.*\s+wrote:.*",
        r"(?i)(<br\s*/?>|<div>| )*-+\s*Original Message\s*-+.*",
        r"(?i)(<br\s*/?>|<div>| )*From:.*Sent:.*To:.*",
    ]

    best_split_point = len(content)

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.DOTALL)
        if match:
            best_split_point = min(best_split_point, match.start())

    if "&gt;" in content:
        lines = content.split("<br>")
        for i, line in enumerate(lines):
            if line.strip().startswith("&gt;"):
                split_point = content.find("<br>" + line) if i > 0 else 0
                if split_point != -1:
                    best_split_point = min(best_split_point, split_point)
                    break

    if best_split_point < len(content):
        return content[:best_split_point].strip(), content[best_split_point:].strip()

    return content, ""


@router.get("/thread/{folder}/{uid}", response_class=HTMLResponse)
async def thread_view(
    request: Request,
    folder: str,
    uid: int,
    unread_only: bool = Query(False),
    load_images: bool = Query(False),
    session: Session = Depends(require_auth),
):
    email = db.get_email(uid, folder)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    labels = email.get("gmail_labels", [])
    if isinstance(labels, str):
        is_starred = "\\Starred" in labels
    else:
        is_starred = "\\Starred" in (labels or [])

    thread_emails = db.get_thread(uid, folder)
    if not thread_emails:
        thread_emails = [email]

    # Get neighbors for navigation
    neighbors = db.get_neighbor_uids(folder, uid, unread_only)

    messages = []
    calendar_invite = None

    for e in thread_emails:
        body_html = e.get("body_html", "")
        body_text = e.get("body_text", "")
        content = (
            sanitize_html(body_html, block_images=not load_images)
            if body_html
            else text_to_html(body_text)
        )

        if not calendar_invite:
            calendar_invite = detect_calendar_invite(e)

        main_content, quoted_content = split_quoted_text(content)

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
                "content": main_content,
                "quoted_content": quoted_content,
                "is_unread": e.get("is_unread", False),
                "has_attachments": e.get("has_attachments", False),
                "attachment_filenames": e.get("attachment_filenames", []),
            }
        )

    return templates.TemplateResponse(
        "thread.html",
        get_template_context(
            request,
            subject=email.get("subject", "(no subject)"),
            messages=messages,
            folder=folder,
            uid=uid,
            is_starred=is_starred,
            load_images=load_images,
            neighbors=neighbors,
            unread_only=unread_only,
            calendar_invite=calendar_invite,
        ),
    )


@router.get("/api/attachment/{folder}/{uid}/{filename}")
async def download_attachment(
    folder: str, uid: int, filename: str, session: Session = Depends(require_auth)
):
    """Proxy attachment downloads from the engine API."""
    engine_url = get_engine_url()
    url = f"{engine_url}/api/email/{folder}/{uid}/attachment/{filename}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30.0)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, detail="Attachment not found"
            )

        return StreamingResponse(
            iter([response.content]),
            media_type=response.headers.get("Content-Type", "application/octet-stream"),
            headers={
                "Content-Disposition": response.headers.get(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
            },
        )


@router.get("/api/attachment/{folder}/{uid}/download-all")
async def download_all_attachments(
    folder: str, uid: int, session: Session = Depends(require_auth)
):
    """Download all attachments as a zip file."""
    import zipfile
    import tempfile
    from pathlib import Path

    engine_url = get_engine_url()

    email = db.get_email(uid, folder)
    if not email or not email.get("attachment_filenames"):
        raise HTTPException(status_code=404, detail="No attachments found")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
        zip_path = Path(tmp_file.name)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            async with httpx.AsyncClient() as client:
                for filename in email["attachment_filenames"]:
                    url = f"{engine_url}/api/email/{folder}/{uid}/attachment/{filename}"
                    response = await client.get(url, timeout=30.0)

                    if response.status_code == 200:
                        zip_file.writestr(filename, response.content)

        def iterfile():
            with open(zip_path, "rb") as f:
                yield from f
            zip_path.unlink()

        return StreamingResponse(
            iterfile(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="attachments_{uid}.zip"'
            },
        )
    except Exception as e:
        if zip_path.exists():
            zip_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))
