from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import re

from workspace_secretary.web import database as db
from workspace_secretary.config import load_config
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_config = None


def get_config():
    global _config
    if _config is None:
        _config = load_config()
    return _config


def analyze_signals(email: dict) -> dict:
    config = get_config()

    from_addr = (email.get("from_addr") or "").lower()
    to_addr = (email.get("to_addr") or "").lower()
    subject = (email.get("subject") or "").lower()
    body = (email.get("body_text") or "").lower()
    text = subject + " " + body

    is_from_vip = any(vip.lower() in from_addr for vip in config.vip_senders)

    is_addressed_to_me = (
        config.identity.matches_email(to_addr.split(",")[0].strip())
        if to_addr
        else False
    )

    mentions_my_name = config.identity.matches_name_part(body)

    question_patterns = [
        r"\?",
        r"\bcan you\b",
        r"\bcould you\b",
        r"\bplease\b",
        r"\bwould you\b",
    ]
    has_question = any(re.search(p, text) for p in question_patterns)

    deadline_patterns = [
        r"\beod\b",
        r"\basap\b",
        r"\burgent\b",
        r"\bdeadline\b",
        r"\bdue\b",
        r"\bby\s+(monday|tuesday|wednesday|thursday|friday|tomorrow|today)",
    ]
    mentions_deadline = any(re.search(p, text) for p in deadline_patterns)

    meeting_patterns = [
        r"\bmeet\b",
        r"\bmeeting\b",
        r"\bschedule\b",
        r"\bcalendar\b",
        r"\binvite\b",
        r"\bzoom\b",
        r"\bgoogle meet\b",
        r"\bcall\b",
    ]
    mentions_meeting = any(re.search(p, text) for p in meeting_patterns)

    return {
        "is_from_vip": is_from_vip,
        "is_addressed_to_me": is_addressed_to_me,
        "mentions_my_name": mentions_my_name,
        "has_question": has_question,
        "mentions_deadline": mentions_deadline,
        "mentions_meeting": mentions_meeting,
        "is_important": email.get("is_important", False),
    }


def compute_priority(signals: dict) -> tuple[str, str]:
    score = 0
    reasons = []

    if signals["is_from_vip"]:
        score += 3
        reasons.append("VIP sender")
    if signals["is_addressed_to_me"]:
        score += 2
        reasons.append("Addressed to you")
    if signals["mentions_my_name"]:
        score += 1
        reasons.append("Mentions your name")
    if signals["has_question"]:
        score += 2
        reasons.append("Contains question")
    if signals["mentions_deadline"]:
        score += 2
        reasons.append("Mentions deadline")
    if signals["is_important"]:
        score += 1
        reasons.append("Marked important")

    if score >= 5:
        priority = "high"
    elif score >= 3:
        priority = "medium"
    else:
        priority = "low"

    return priority, ", ".join(reasons) if reasons else "No priority signals"


@router.get("/api/analysis/{folder}/{uid}", response_class=JSONResponse)
async def get_email_analysis(
    folder: str, uid: int, session: Session = Depends(require_auth)
):
    email = db.get_email(uid, folder)
    if not email:
        return JSONResponse({"error": "Email not found"}, status_code=404)

    signals = analyze_signals(email)
    priority, priority_reason = compute_priority(signals)

    related = []
    if db.has_embeddings():
        try:
            related = db.find_related_emails(uid, folder, limit=5)
        except Exception:
            pass

    suggested_actions = []
    if signals["has_question"]:
        suggested_actions.append(
            {"action": "reply", "label": "Draft Reply", "icon": "💬"}
        )
    if signals["mentions_meeting"]:
        suggested_actions.append(
            {"action": "calendar", "label": "Check Calendar", "icon": "📅"}
        )
    if signals["mentions_deadline"]:
        suggested_actions.append(
            {"action": "task", "label": "Create Task", "icon": "✅"}
        )
    if not signals["is_addressed_to_me"] and not signals["mentions_my_name"]:
        suggested_actions.append(
            {"action": "archive", "label": "Archive (FYI only)", "icon": "📥"}
        )

    return {
        "signals": signals,
        "priority": priority,
        "priority_reason": priority_reason,
        "related_emails": [
            {
                "uid": r["uid"],
                "folder": r["folder"],
                "from": r["from_addr"],
                "subject": r["subject"],
                "preview": r["preview"],
                "similarity": round(r["similarity"] * 100),
            }
            for r in related
        ],
        "suggested_actions": suggested_actions,
        "has_embeddings": db.has_embeddings(),
    }


@router.get("/analysis/{folder}/{uid}", response_class=HTMLResponse)
async def analysis_sidebar(
    request: Request, folder: str, uid: int, session: Session = Depends(require_auth)
):
    email = db.get_email(uid, folder)
    if not email:
        return HTMLResponse("<div class='p-4 text-red-400'>Email not found</div>")

    signals = analyze_signals(email)
    priority, priority_reason = compute_priority(signals)

    related = []
    if db.has_embeddings():
        try:
            related = db.find_related_emails(uid, folder, limit=5)
        except Exception:
            pass

    suggested_actions = []
    if signals["has_question"]:
        suggested_actions.append(
            {"action": "reply", "label": "Draft Reply", "icon": "💬"}
        )
    if signals["mentions_meeting"]:
        suggested_actions.append(
            {"action": "calendar", "label": "Check Calendar", "icon": "📅"}
        )
    if signals["mentions_deadline"]:
        suggested_actions.append(
            {"action": "task", "label": "Create Task", "icon": "✅"}
        )

    return templates.TemplateResponse(
        "partials/analysis_sidebar.html",
        {
            "request": request,
            "signals": signals,
            "priority": priority,
            "priority_reason": priority_reason,
            "related_emails": related,
            "suggested_actions": suggested_actions,
            "has_embeddings": db.has_embeddings(),
            "folder": folder,
            "uid": uid,
        },
    )
