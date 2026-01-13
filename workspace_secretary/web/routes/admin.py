from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime, timedelta, timezone

from workspace_secretary.web import database as db
from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session
from workspace_secretary.web.alerting import check_and_alert

router = APIRouter()


def get_mutation_stats() -> dict:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            now = datetime.now(timezone.utc)
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)

            cur.execute(
                "SELECT COUNT(*) FROM mutation_journal WHERE status = 'PENDING'"
            )
            row = cur.fetchone()
            pending = row[0] if row else 0

            cur.execute(
                "SELECT COUNT(*) FROM mutation_journal WHERE status = 'PENDING' AND created_at < %s",
                (hour_ago,),
            )
            row = cur.fetchone()
            stuck = row[0] if row else 0

            cur.execute(
                "SELECT COUNT(*) FROM mutation_journal WHERE status = 'FAILED' AND created_at > %s",
                (day_ago,),
            )
            row = cur.fetchone()
            failed_24h = row[0] if row else 0

            cur.execute(
                "SELECT COUNT(*) FROM mutation_journal WHERE status = 'COMPLETED' AND created_at > %s",
                (day_ago,),
            )
            row = cur.fetchone()
            completed_24h = row[0] if row else 0

            cur.execute(
                """
                SELECT id, email_uid, email_folder, action, status, error, created_at
                FROM mutation_journal
                WHERE status IN ('PENDING', 'FAILED')
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
            columns = [desc[0] for desc in (cur.description or [])]
            recent_issues = [dict(zip(columns, row)) for row in cur.fetchall()]

            return {
                "pending": pending,
                "stuck": stuck,
                "failed_24h": failed_24h,
                "completed_24h": completed_24h,
                "recent_issues": recent_issues,
                "health": "critical"
                if stuck > 0 or failed_24h > 5
                else "warning"
                if failed_24h > 0
                else "healthy",
            }


def get_sync_stats() -> dict:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT folder, last_sync 
                FROM folder_state 
                ORDER BY last_sync DESC NULLS LAST
                LIMIT 1
                """
            )
            row = cur.fetchone()
            last_sync = row[1] if row else None
            last_sync_folder = row[0] if row else None

            cur.execute("SELECT COUNT(*) FROM folder_state")
            row = cur.fetchone()
            folder_count = row[0] if row else 0

            day_ago = datetime.now(timezone.utc) - timedelta(days=1)
            cur.execute(
                "SELECT COUNT(*) FROM sync_errors WHERE created_at > %s AND resolved_at IS NULL",
                (day_ago,),
            )
            row = cur.fetchone()
            unresolved_errors = row[0] if row else 0

            cur.execute(
                """
                SELECT id, folder, email_uid, error_type, error_message, created_at
                FROM sync_errors
                WHERE resolved_at IS NULL
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            columns = [desc[0] for desc in (cur.description or [])]
            recent_errors = [dict(zip(columns, row)) for row in cur.fetchall()]

            sync_age_minutes = None
            if last_sync:
                if isinstance(last_sync, str):
                    last_sync = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=timezone.utc)
                sync_age_minutes = int((now - last_sync).total_seconds() / 60)

            return {
                "last_sync": last_sync,
                "last_sync_folder": last_sync_folder,
                "sync_age_minutes": sync_age_minutes,
                "folder_count": folder_count,
                "unresolved_errors": unresolved_errors,
                "recent_errors": recent_errors,
                "health": "critical"
                if sync_age_minutes and sync_age_minutes > 30
                else "warning"
                if unresolved_errors > 0
                else "healthy",
            }


def get_db_stats() -> dict:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM emails")
            row = cur.fetchone()
            total_emails = row[0] if row else 0

            cur.execute("SELECT COUNT(DISTINCT folder) FROM emails")
            row = cur.fetchone()
            folder_count = row[0] if row else 0

            cur.execute("SELECT COUNT(*) FROM emails WHERE is_unread = true")
            row = cur.fetchone()
            unread_count = row[0] if row else 0

            cur.execute(
                """
                SELECT folder, COUNT(*) as count 
                FROM emails 
                GROUP BY folder 
                ORDER BY count DESC
                LIMIT 10
                """
            )
            folder_breakdown = [
                {"folder": row[0], "count": row[1]} for row in cur.fetchall()
            ]

            return {
                "total_emails": total_emails,
                "folder_count": folder_count,
                "unread_count": unread_count,
                "folder_breakdown": folder_breakdown,
            }


def get_integrity_stats() -> dict:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    fs.folder,
                    fs.uidnext,
                    fs.last_sync,
                    COALESCE(e.email_count, 0) as db_count
                FROM folder_state fs
                LEFT JOIN (
                    SELECT folder, COUNT(*) as email_count
                    FROM emails
                    GROUP BY folder
                ) e ON fs.folder = e.folder
                ORDER BY fs.folder
                """
            )
            columns = [desc[0] for desc in (cur.description or [])]
            folder_integrity = [dict(zip(columns, row)) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT COUNT(*) FROM emails e
                WHERE NOT EXISTS (
                    SELECT 1 FROM folder_state fs WHERE fs.folder = e.folder
                )
                """
            )
            row = cur.fetchone()
            orphaned_emails = row[0] if row else 0

            return {
                "folder_integrity": folder_integrity,
                "orphaned_emails": orphaned_emails,
                "health": "warning" if orphaned_emails > 0 else "healthy",
            }


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    session: Session = Depends(require_auth),
):
    mutation_stats = get_mutation_stats()
    sync_stats = get_sync_stats()
    db_stats = get_db_stats()
    integrity_stats = get_integrity_stats()

    overall_health = "healthy"
    if mutation_stats["health"] == "critical" or sync_stats["health"] == "critical":
        overall_health = "critical"
    elif (
        mutation_stats["health"] == "warning"
        or sync_stats["health"] == "warning"
        or integrity_stats["health"] == "warning"
    ):
        overall_health = "warning"

    alerts = []
    if mutation_stats["stuck"] > 0:
        alerts.append(
            {
                "level": "critical",
                "message": f"{mutation_stats['stuck']} mutation(s) stuck for over 1 hour",
                "action": "Check engine connection",
            }
        )
    if mutation_stats["failed_24h"] > 0:
        alerts.append(
            {
                "level": "warning",
                "message": f"{mutation_stats['failed_24h']} failed mutation(s) in last 24h",
                "action": "Review failed mutations below",
            }
        )
    if sync_stats["sync_age_minutes"] and sync_stats["sync_age_minutes"] > 30:
        alerts.append(
            {
                "level": "critical",
                "message": f"Last sync was {sync_stats['sync_age_minutes']} minutes ago",
                "action": "Check engine status",
            }
        )
    if sync_stats["unresolved_errors"] > 0:
        alerts.append(
            {
                "level": "warning",
                "message": f"{sync_stats['unresolved_errors']} unresolved sync error(s)",
                "action": "Review sync errors below",
            }
        )

    if integrity_stats["orphaned_emails"] > 0:
        alerts.append(
            {
                "level": "warning",
                "message": f"{integrity_stats['orphaned_emails']} email(s) in folders with no sync state",
                "action": "Run full sync to reconcile",
            }
        )

    if overall_health == "critical":
        check_and_alert(mutation_stats, sync_stats)

    return templates.TemplateResponse(
        "admin.html",
        get_template_context(
            request,
            overall_health=overall_health,
            alerts=alerts,
            mutation_stats=mutation_stats,
            sync_stats=sync_stats,
            db_stats=db_stats,
            integrity_stats=integrity_stats,
        ),
    )


@router.get("/api/activity/log")
async def activity_log(session: Session = Depends(require_auth)):
    """Get recent activity log from mutation journal."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email_uid, email_folder, action, status, error, created_at, completed_at
                FROM mutation_journal
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            columns = [desc[0] for desc in (cur.description or [])]
            log_entries = [dict(zip(columns, row)) for row in cur.fetchall()]

            # Convert datetimes to isoformat
            for entry in log_entries:
                if entry.get("created_at"):
                    entry["created_at"] = entry["created_at"].isoformat()
                if entry.get("completed_at"):
                    entry["completed_at"] = entry["completed_at"].isoformat()

            return JSONResponse({"status": "ok", "log": log_entries})
