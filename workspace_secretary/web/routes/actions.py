from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from workspace_secretary.web import engine_client as engine
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter(prefix="/api/email")


@router.post("/toggle-read/{folder}/{uid}")
async def toggle_read(
    folder: str,
    uid: int,
    mark_unread: bool = Query(False),
    session: Session = Depends(require_auth),
):
    if mark_unread:
        result = await engine.mark_unread(uid, folder)
    else:
        result = await engine.mark_read(uid, folder)
    return JSONResponse(result)


@router.post("/move/{folder}/{uid}")
async def move_email(
    folder: str,
    uid: int,
    destination: str = Query(...),
    session: Session = Depends(require_auth),
):
    result = await engine.move_email(uid, folder, destination)
    return JSONResponse(result)


@router.post("/delete/{folder}/{uid}")
async def delete_email(folder: str, uid: int, session: Session = Depends(require_auth)):
    result = await engine.delete_email(uid, folder)
    return JSONResponse(result)


@router.post("/labels/{folder}/{uid}")
async def modify_labels(
    folder: str,
    uid: int,
    labels: str = Query(...),
    action: str = Query("add"),
    session: Session = Depends(require_auth),
):
    label_list = [l.strip() for l in labels.split(",") if l.strip()]
    result = await engine.modify_labels(uid, folder, label_list, action)
    return JSONResponse(result)


@router.post("/spam/{folder}/{uid}")
async def mark_spam(folder: str, uid: int, session: Session = Depends(require_auth)):
    result = await engine.move_email(uid, folder, "[Gmail]/Spam")
    return JSONResponse(result)


@router.post("/mute/{folder}/{uid}")
async def mute_thread(folder: str, uid: int, session: Session = Depends(require_auth)):
    result = await engine.modify_labels(uid, folder, ["Muted"], "add")
    return JSONResponse(result)


@router.post("/snooze/{folder}/{uid}")
async def snooze_email(
    folder: str,
    uid: int,
    until: str = Query(...),
    session: Session = Depends(require_auth),
):
    result = await engine.modify_labels(uid, folder, ["Snoozed"], "add")
    return JSONResponse(
        {"success": True, "message": f"Snoozed until {until}", "snooze_time": until}
    )


@router.post("/remind/{folder}/{uid}")
async def remind_email(
    folder: str,
    uid: int,
    when: str = Query(...),
    session: Session = Depends(require_auth),
):
    result = await engine.modify_labels(uid, folder, ["Reminder"], "add")
    return JSONResponse(
        {"success": True, "message": f"Reminder set for {when}", "reminder_time": when}
    )
