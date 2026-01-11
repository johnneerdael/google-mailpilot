from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from workspace_secretary.web import database as db
from workspace_secretary.web.auth import Session, require_auth

router = APIRouter()


@router.get("/api/sync/status")
async def get_sync_status(
    session: Session = Depends(require_auth),
    folder_limit: int = Query(50, ge=1, le=200),
    error_limit: int = Query(20, ge=1, le=200),
):
    try:
        with db.get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT folder, uidvalidity, uidnext, highestmodseq, last_sync
                    FROM folder_state
                    ORDER BY last_sync DESC NULLS LAST, folder ASC
                    LIMIT %s
                    """,
                    (folder_limit,),
                )
                folders = cur.fetchall()

                cur.execute(
                    """
                    SELECT id, folder, email_uid, error_type, error_message, created_at, resolved_at
                    FROM sync_errors
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (error_limit,),
                )
                errors = cur.fetchall()

                cur.execute(
                    """
                    SELECT component, metric, value, recorded_at
                    FROM system_health
                    ORDER BY recorded_at DESC
                    LIMIT 50
                    """
                )
                recent_metrics = cur.fetchall()

        last_sync = None
        if folders:
            last_sync = folders[0].get("last_sync")

        now = datetime.now(timezone.utc)
        sync_age_seconds = None
        if last_sync:
            if isinstance(last_sync, str):
                last_sync = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=timezone.utc)
            sync_age_seconds = int((now - last_sync).total_seconds())

        unresolved_errors = sum(1 for e in errors if e.get("resolved_at") is None)

        health = "healthy"
        if sync_age_seconds is not None and sync_age_seconds > 1800:
            health = "critical"
        elif unresolved_errors > 0:
            health = "warning"

        return JSONResponse(
            {
                "status": "ok",
                "health": health,
                "sync": {
                    "last_sync": last_sync.isoformat() if last_sync else None,
                    "sync_age_seconds": sync_age_seconds,
                    "folders": folders,
                    "folder_limit": folder_limit,
                },
                "errors": {
                    "items": errors,
                    "unresolved": unresolved_errors,
                    "error_limit": error_limit,
                },
                "metrics": {
                    "recent": recent_metrics,
                    "limit": 50,
                },
            }
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/activity/log")
async def get_activity_log(
    session: Session = Depends(require_auth),
    limit: int = Query(50, ge=1, le=200),
    include_email: bool = Query(False),
):
    try:
        with db.get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, email_uid, email_folder, action, status, error, created_at, updated_at
                    FROM mutation_journal
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                items = cur.fetchall()

                if include_email and items:
                    keys = {(i.get("email_uid"), i.get("email_folder")) for i in items}
                    uids = [k[0] for k in keys if k[0] is not None and k[1] is not None]
                    folders = [
                        k[1] for k in keys if k[0] is not None and k[1] is not None
                    ]

                    email_map: dict[tuple[int, str], dict] = {}
                    if uids and len(set(folders)) == 1:
                        folder = folders[0]
                        cur.execute(
                            """
                            SELECT uid, folder, from_addr, subject, date
                            FROM emails
                            WHERE folder = %s AND uid = ANY(%s)
                            """,
                            (folder, uids),
                        )
                        for e in cur.fetchall():
                            email_map[(e["uid"], e["folder"])] = e
                    else:
                        for uid, folder in keys:
                            if uid is None or folder is None:
                                continue
                            cur.execute(
                                """
                                SELECT uid, folder, from_addr, subject, date
                                FROM emails
                                WHERE uid = %s AND folder = %s
                                """,
                                (uid, folder),
                            )
                            e = cur.fetchone()
                            if e:
                                email_map[(uid, folder)] = e

                    for item in items:
                        k = (item.get("email_uid"), item.get("email_folder"))
                        item["email"] = email_map.get(k)

        return JSONResponse(
            {
                "status": "ok",
                "items": items,
                "limit": limit,
                "ordering": "created_at desc",
                "include_email": include_email,
            }
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
