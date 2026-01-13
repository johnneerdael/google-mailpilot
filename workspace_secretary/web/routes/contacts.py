"""
Contact extraction and management routes.
"""

import asyncio
from fastapi import APIRouter, Request, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from workspace_secretary.web.auth import Session, require_auth
from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.database import (
    upsert_contact,
    add_contact_interaction,
    get_all_contacts,
    get_contact_by_email,
    get_contact_interactions,
    get_frequent_contacts,
    get_recent_contacts,
    search_contacts_autocomplete,
    update_contact_vip_status,
    add_contact_note,
    get_contact_notes,
    get_email,
    get_pool,
)
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def parse_email_address(addr_str: str):
    """Parse 'Name <email@example.com>' or 'email@example.com' format."""
    if not addr_str:
        return None, None

    match = re.match(r"^(.*?)\s*<(.+?)>$", addr_str.strip())
    if match:
        display_name = match.group(1).strip().strip('"')
        email = match.group(2).strip().lower()
        return display_name, email

    email = addr_str.strip().lower()
    return None, email


def extract_name_parts(display_name: str):
    """Extract first and last name from display name."""
    if not display_name:
        return None, None

    parts = display_name.split()
    if len(parts) == 0:
        return None, None
    elif len(parts) == 1:
        return parts[0], None
    else:
        return parts[0], parts[-1]


@router.post("/api/contacts/sync")
async def sync_contacts_from_emails(
    session: Session = Depends(require_auth),
    limit: int = Query(1000),
):
    """Extract contacts from recent emails."""

    def _sync_contacts_blocking(limit: int) -> dict:
        from workspace_secretary.web.database import get_pool
        from psycopg.rows import dict_row

        pool = get_pool()
        contact_count = 0

        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT uid, folder, from_addr, to_addr, cc_addr, subject, date, message_id
                    FROM emails
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                emails = cur.fetchall()

        for email in emails:
            for addr_str in [
                email.get("from_addr"),
                email.get("to_addr"),
                email.get("cc_addr"),
            ]:
                if not addr_str:
                    continue

                for single_addr in addr_str.split(","):
                    display_name, email_addr = parse_email_address(single_addr)
                    if not email_addr:
                        continue

                    first_name, last_name = (
                        extract_name_parts(display_name)
                        if display_name
                        else (None, None)
                    )

                    contact_id = upsert_contact(
                        email=email_addr,
                        display_name=display_name or email_addr,
                        first_name=first_name,
                        last_name=last_name,
                    )

                    if contact_id is None:
                        continue

                    direction = "received"
                    from_addr = email.get("from_addr")
                    to_addr = email.get("to_addr")
                    cc_addr = email.get("cc_addr")

                    if from_addr and email_addr in from_addr:
                        direction = "received"
                    elif to_addr and email_addr in to_addr:
                        direction = "sent"
                    elif cc_addr and email_addr in cc_addr:
                        direction = "cc"

                    add_contact_interaction(
                        contact_id=contact_id,
                        email_uid=email["uid"],
                        email_folder=email["folder"],
                        direction=direction,
                        subject=email.get("subject") or "(No subject)",
                        email_date=email["date"],
                        message_id=email.get("message_id") or "",
                    )

                    contact_count += 1

        return {
            "success": True,
            "contacts_synced": contact_count,
            "emails_processed": len(emails),
        }

    try:
        result = await asyncio.to_thread(_sync_contacts_blocking, limit)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error syncing contacts: {e}", exc_info=True)
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=500,
        )


@router.get("/contacts", response_class=HTMLResponse)
async def contacts_page(
    request: Request,
    session: Session = Depends(require_auth),
    search: str = Query(None),
    sort: str = Query("last_email_date"),
    page: int = Query(1),
):
    """Contacts list page."""
    limit = 50
    offset = (page - 1) * limit

    contacts = get_all_contacts(limit=limit, offset=offset, search=search, sort_by=sort)
    frequent = get_frequent_contacts(limit=10)
    recent = get_recent_contacts(limit=10)

    return templates.TemplateResponse(
        "contacts.html",
        get_template_context(
            request,
            contacts=contacts,
            frequent=frequent,
            recent=recent,
            search=search or "",
            sort=sort,
            page=page,
        ),
    )


@router.get("/contacts/{email:path}", response_class=HTMLResponse)
async def contact_detail_page(
    request: Request,
    email: str,
    session: Session = Depends(require_auth),
):
    contact = get_contact_by_email(email)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    interactions = get_contact_interactions(contact["id"], limit=100)
    notes = get_contact_notes(contact["id"])

    return templates.TemplateResponse(
        "contact_detail.html",
        get_template_context(
            request,
            contact=contact,
            interactions=interactions,
            notes=notes,
        ),
    )


@router.post("/api/contacts/{contact_id}/vip")
async def toggle_vip_status(
    contact_id: int,
    is_vip: bool = Query(...),
    session: Session = Depends(require_auth),
):
    """Toggle VIP status."""
    try:
        update_contact_vip_status(contact_id, is_vip)
        return JSONResponse({"success": True, "is_vip": is_vip})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/contacts/{contact_id}/notes")
async def add_note(
    contact_id: int,
    note: str = Query(...),
    session: Session = Depends(require_auth),
):
    """Add a note to a contact."""
    try:
        note_id = add_contact_note(contact_id, note)
        return JSONResponse({"success": True, "note_id": note_id})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/contacts/autocomplete")
async def contacts_autocomplete(
    q: str = Query(...),
    session: Session = Depends(require_auth),
):
    """Autocomplete search for contacts."""
    try:
        results = search_contacts_autocomplete(q, limit=10)
        return JSONResponse(
            {
                "success": True,
                "contacts": [
                    {
                        "email": r["email"],
                        "name": r["display_name"] or r["email"],
                        "count": r["email_count"],
                    }
                    for r in results
                ],
            }
        )
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
