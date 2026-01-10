from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import List

from workspace_secretary.web import engine_client

router = APIRouter()


@router.post("/api/bulk/mark-read")
async def bulk_mark_read(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.mark_read(int(email["uid"]), email["folder"])
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Marked {success_count} emails as read",
            "count": success_count,
        }
    )


@router.post("/api/bulk/mark-unread")
async def bulk_mark_unread(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.mark_unread(int(email["uid"]), email["folder"])
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Marked {success_count} emails as unread",
            "count": success_count,
        }
    )


@router.post("/api/bulk/archive")
async def bulk_archive(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.move_email(
                int(email["uid"]), email["folder"], "[Gmail]/All Mail"
            )
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Archived {success_count} emails",
            "count": success_count,
        }
    )


@router.post("/api/bulk/delete")
async def bulk_delete(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.move_email(
                int(email["uid"]), email["folder"], "[Gmail]/Trash"
            )
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Deleted {success_count} emails",
            "count": success_count,
            "deleted": uids,
        }
    )


@router.post("/api/bulk/move")
async def bulk_move(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])
    destination = data.get("destination", "")

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )
    if not destination:
        return JSONResponse(
            {"status": "error", "message": "No destination folder"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.move_email(
                int(email["uid"]), email["folder"], destination
            )
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Moved {success_count} emails to {destination}",
            "count": success_count,
        }
    )


@router.post("/api/bulk/label")
async def bulk_label(request: Request):
    data = await request.json()
    uids: List[dict] = data.get("emails", [])
    label = data.get("label", "")

    if not uids:
        return JSONResponse(
            {"status": "error", "message": "No emails selected"}, status_code=400
        )
    if not label:
        return JSONResponse(
            {"status": "error", "message": "No label specified"}, status_code=400
        )

    success_count = 0
    for email in uids:
        try:
            await engine_client.modify_labels(
                int(email["uid"]), email["folder"], [label], "add"
            )
            success_count += 1
        except Exception:
            pass

    return JSONResponse(
        {
            "status": "success",
            "message": f"Added label '{label}' to {success_count} emails",
            "count": success_count,
        }
    )
