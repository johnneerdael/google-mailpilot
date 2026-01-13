from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import JSONResponse
import logging

from workspace_secretary.web import engine_client as engine
from workspace_secretary.web.auth import require_auth, Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email")


@router.post("/toggle-read/{folder}/{uid}")
async def toggle_read(
    folder: str,
    uid: int,
    mark_unread: bool = Query(False),
    session: Session = Depends(require_auth),
):
    try:
        if mark_unread:
            result = await engine.mark_unread(uid, folder)
        else:
            result = await engine.mark_read(uid, folder)
        return JSONResponse({"success": True, **result})
    except HTTPException as e:
        logger.warning(f"Failed to toggle read uid={uid} folder={folder}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error toggling read uid={uid} folder={folder}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/move/{folder}/{uid}")
async def move_email(
    folder: str,
    uid: int,
    destination: str = Query(...),
    session: Session = Depends(require_auth),
):
    try:
        result = await engine.move_email(uid, folder, destination)

        # If moving to trash, provide an undo action
        if "Trash" in destination and result.get("success"):
            # The 'folder' for the undo action is the current destination (trash)
            # The 'destination' for the undo action is the original folder
            # We need to URL-encode slashes in folder names for the path part
            encoded_dest = destination.replace("/", "%2F")
            encoded_folder = folder.replace("/", "%2F")
            undo_url = (
                f"/api/email/move/{encoded_dest}/{uid}?destination={encoded_folder}"
            )

            return JSONResponse(
                {
                    "success": True,
                    "undo_message": "Moved to Trash",
                    "undo_action": {"url": undo_url},
                }
            )

        # For other moves, just return the standard message if there is one
        if result.get("success"):
            return JSONResponse(
                {
                    "success": True,
                    "message": result.get("message", "Email moved successfully."),
                }
            )

        return JSONResponse(result)
    except HTTPException as e:
        logger.warning(f"Failed to move email uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error moving email uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/delete/{folder}/{uid}")
async def delete_email(folder: str, uid: int, session: Session = Depends(require_auth)):
    try:
        result = await engine.delete_email(uid, folder)
        return JSONResponse({"success": True, **result})
    except HTTPException as e:
        logger.warning(f"Failed to delete email uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting email uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/labels/{folder}/{uid}")
async def modify_labels(
    folder: str,
    uid: int,
    labels: str = Query(...),
    action: str = Query("add"),
    session: Session = Depends(require_auth),
):
    try:
        label_list = [l.strip() for l in labels.split(",") if l.strip()]
        result = await engine.modify_labels(uid, folder, label_list, action)
        return JSONResponse({"success": True, **result})
    except HTTPException as e:
        logger.warning(f"Failed to modify labels uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error modifying labels uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/spam/{folder}/{uid}")
async def mark_spam(folder: str, uid: int, session: Session = Depends(require_auth)):
    try:
        result = await engine.move_email(uid, folder, "[Gmail]/Spam")
        return JSONResponse({"success": True, **result})
    except HTTPException as e:
        logger.warning(f"Failed to mark as spam uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error marking spam uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/mute/{folder}/{uid}")
async def mute_thread(folder: str, uid: int, session: Session = Depends(require_auth)):
    try:
        result = await engine.modify_labels(uid, folder, ["Muted"], "add")
        return JSONResponse({"success": True, **result})
    except HTTPException as e:
        logger.warning(f"Failed to mute thread uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error muting thread uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/snooze/{folder}/{uid}")
async def snooze_email(
    folder: str,
    uid: int,
    until: str = Query(...),
    session: Session = Depends(require_auth),
):
    try:
        result = await engine.modify_labels(uid, folder, ["Snoozed"], "add")
        return JSONResponse(
            {"success": True, "message": f"Snoozed until {until}", "snooze_time": until}
        )
    except HTTPException as e:
        logger.warning(f"Failed to snooze email uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error snoozing email uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/remind/{folder}/{uid}")
async def remind_email(
    folder: str,
    uid: int,
    when: str = Query(...),
    session: Session = Depends(require_auth),
):
    try:
        result = await engine.modify_labels(uid, folder, ["Reminder"], "add")
        return JSONResponse(
            {
                "success": True,
                "message": f"Reminder set for {when}",
                "reminder_time": when,
            }
        )
    except HTTPException as e:
        logger.warning(f"Failed to set reminder uid={uid}: {e.detail}")
        return JSONResponse(
            {"success": False, "error": str(e.detail)}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Unexpected error setting reminder uid={uid}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
