from fastapi import APIRouter, Request, Query, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional, List
import logging

from workspace_secretary.web import database as db
from workspace_secretary.web import engine_client as engine
from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/compose", response_class=HTMLResponse)
async def compose_modal(
    request: Request,
    reply_to: Optional[int] = Query(None),
    reply_all: Optional[int] = Query(None),
    forward: Optional[int] = Query(None),
    folder: str = Query("INBOX"),
    session: Session = Depends(require_auth),
):
    signature = "\n\n--\nSent from Gmail Secretary"

    is_htmx_request = request.headers.get("HX-Request") == "true"

    context = {
        "request": request,
        "mode": "new",
        "to": "",
        "cc": "",
        "bcc": "",
        "subject": "",
        "body": signature,
        "reply_to_uid": None,
        "reply_to_folder": folder,
        "original_message_id": None,
        "is_modal": is_htmx_request,
    }

    # Determine mode and pre-populate fields
    uid = reply_to or reply_all or forward
    if uid:
        # Fetch original email for reply/forward context
        try:
            email = db.get_email(uid, folder)
        except Exception as e:
            logger.warning(f"Failed to fetch email uid={uid} folder={folder}: {e}")
            email = None

        if email:
            from_addr = email.get("from_addr", "")
            to_addr = email.get("to_addr", "")
            cc_addr = email.get("cc_addr", "")
            subject = email.get("subject", "")
            body_text = email.get("body_text", "") or email.get("body_html", "")
            date = email.get("date", "")
            message_id = email.get("message_id", "")

            # Format quoted text
            quoted_header = f"\n\nOn {date}, {from_addr} wrote:\n"
            quoted_body = "\n".join(f"> {line}" for line in body_text.split("\n")[:50])

            if reply_to:
                context.update(
                    {
                        "mode": "reply",
                        "to": from_addr,
                        "subject": f"Re: {subject}"
                        if not subject.lower().startswith("re:")
                        else subject,
                        "body": quoted_header + quoted_body,
                        "reply_to_uid": uid,
                        "original_message_id": message_id,
                    }
                )
            elif reply_all:
                # Include original recipients minus self
                all_recipients = [from_addr]
                if to_addr:
                    all_recipients.extend([a.strip() for a in to_addr.split(",")])
                # Remove duplicates and self (we'd need user email from config)
                unique_recipients = list(dict.fromkeys(all_recipients))

                context.update(
                    {
                        "mode": "reply_all",
                        "to": ", ".join(unique_recipients[:5]),  # Limit to 5 for UI
                        "cc": cc_addr or "",
                        "subject": f"Re: {subject}"
                        if not subject.lower().startswith("re:")
                        else subject,
                        "body": quoted_header + quoted_body,
                        "reply_to_uid": uid,
                        "original_message_id": message_id,
                    }
                )
            elif forward:
                forward_header = f"\n\n---------- Forwarded message ----------\nFrom: {from_addr}\nDate: {date}\nSubject: {subject}\nTo: {to_addr}\n\n"
                context.update(
                    {
                        "mode": "forward",
                        "subject": f"Fwd: {subject}"
                        if not subject.lower().startswith("fwd:")
                        else subject,
                        "body": forward_header + body_text[:5000],  # Limit forward body
                        "reply_to_uid": uid,
                    }
                )

    template_name = "compose.html" if is_htmx_request else "compose_page.html"
    return templates.TemplateResponse(template_name, get_template_context(**context))


@router.post("/api/email/send")
async def send_email(
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    cc: Optional[str] = Form(None),
    bcc: Optional[str] = Form(None),
    reply_to_message_id: Optional[str] = Form(None),
    attachments: List[UploadFile] = File(default=[]),
    schedule_time: Optional[str] = Form(None),
    session: Session = Depends(require_auth),
):
    try:
        if attachments:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Attachment support coming soon - engine needs update",
                },
                status_code=501,
            )

        if schedule_time:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Scheduled send coming soon - needs queue implementation",
                },
                status_code=501,
            )

        result = await engine.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc or None,
            bcc=bcc or None,
            reply_to_message_id=reply_to_message_id or None,
        )
        return JSONResponse({"success": True, "message": "Email sent successfully"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/contacts/autocomplete")
async def contacts_autocomplete(
    q: str = Query(..., min_length=1),
    session: Session = Depends(require_auth),
):
    emails_raw = db.get_inbox_emails("INBOX", limit=100, offset=0)
    contacts = set()
    for email in emails_raw:
        addr = email.get("from_addr", "")
        if addr and q.lower() in addr.lower():
            contacts.add(addr)
        if len(contacts) >= 10:
            break
    return JSONResponse({"contacts": list(contacts)})


@router.post("/api/email/draft")
async def save_draft(
    uid: int = Form(...),
    folder: str = Form(...),
    body: str = Form(...),
    reply_all: bool = Form(False),
    session: Session = Depends(require_auth),
):
    """Save a draft reply via Engine API."""
    try:
        result = await engine.create_draft_reply(
            uid=uid,
            folder=folder,
            body=body,
            reply_all=reply_all,
        )
        return JSONResponse({"success": True, "message": "Draft saved"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
