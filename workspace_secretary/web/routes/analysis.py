from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
import re
import idna
from email.utils import parseaddr

from workspace_secretary.web import database as db
from workspace_secretary.web import templates, get_template_context
from workspace_secretary.config import load_config
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()

_config = None


def get_config():
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _parse_authentication_results(headers: dict) -> dict:
    raw_values: list[str] = []
    for k in ["Authentication-Results", "ARC-Authentication-Results", "Received-SPF"]:
        v = headers.get(k) if isinstance(headers, dict) else None
        if not v:
            continue
        if isinstance(v, list):
            raw_values.extend([str(x) for x in v if x])
        else:
            raw_values.append(str(v))

    combined = "\n".join(raw_values)
    combined_l = combined.lower()

    def _has_result(prefix: str, value: str) -> bool:
        return bool(
            re.search(rf"\b{re.escape(prefix)}\s*=\s*{re.escape(value)}\b", combined_l)
        )

    spf_pass = _has_result("spf", "pass") or _has_result("spf", "bestguesspass")
    spf_fail = _has_result("spf", "fail") or _has_result("spf", "softfail")
    dkim_pass = _has_result("dkim", "pass")
    dkim_fail = _has_result("dkim", "fail")
    dmarc_pass = _has_result("dmarc", "pass")
    dmarc_fail = _has_result("dmarc", "fail")

    return {
        "auth_results_raw": combined or None,
        "spf": "pass" if spf_pass else "fail" if spf_fail else "unknown",
        "dkim": "pass" if dkim_pass else "fail" if dkim_fail else "unknown",
        "dmarc": "pass" if dmarc_pass else "fail" if dmarc_fail else "unknown",
    }


def _extract_domain(addr: str) -> str:
    _, email_addr = parseaddr(addr or "")
    if "@" not in email_addr:
        return ""
    return email_addr.split("@", 1)[1].strip().lower()


def _is_punycode_domain(domain: str) -> bool:
    if not domain:
        return False
    try:
        decoded = idna.decode(domain)
        return decoded != domain
    except Exception:
        return "xn--" in domain


def _sender_suspicion_signals(email: dict) -> dict:
    from_addr_raw = email.get("from_addr") or ""
    headers_obj = email.get("headers")
    headers = headers_obj if isinstance(headers_obj, dict) else {}
    reply_to_raw = headers.get("Reply-To")

    from_domain = _extract_domain(from_addr_raw)
    reply_to_domain = _extract_domain(str(reply_to_raw) if reply_to_raw else "")

    reply_to_differs = bool(
        reply_to_domain and from_domain and reply_to_domain != from_domain
    )

    display_name, parsed_addr = parseaddr(from_addr_raw)
    display_name_l = (display_name or "").lower()
    parsed_local = parsed_addr.split("@", 1)[0].lower() if "@" in parsed_addr else ""

    display_name_mismatch = False
    if display_name_l and parsed_local:
        token = re.sub(r"[^a-z0-9]+", "", parsed_local)
        if token and token not in re.sub(r"[^a-z0-9]+", "", display_name_l):
            display_name_mismatch = True

    punycode_domain = _is_punycode_domain(from_domain) or _is_punycode_domain(
        reply_to_domain
    )

    return {
        "reply_to_differs": reply_to_differs,
        "display_name_mismatch": display_name_mismatch,
        "punycode_domain": punycode_domain,
        "is_suspicious_sender": bool(
            reply_to_differs or display_name_mismatch or punycode_domain
        ),
    }


def analyze_signals(email: dict) -> dict:
    config = get_config()

    from_addr = (email.get("from_addr") or "").lower()
    to_addr = (email.get("to_addr") or "").lower()
    subject = (email.get("subject") or "").lower()
    body = (email.get("body_text") or "").lower()
    text = subject + " " + body

    auth_results_raw = email.get("auth_results_raw")
    spf = email.get("spf")
    dkim = email.get("dkim")
    dmarc = email.get("dmarc")

    headers_obj = email.get("headers")
    headers = headers_obj if isinstance(headers_obj, dict) else {}
    auth = (
        _parse_authentication_results(headers)
        if auth_results_raw is None and spf is None and dkim is None and dmarc is None
        else {
            "auth_results_raw": auth_results_raw,
            "spf": spf or "unknown",
            "dkim": dkim or "unknown",
            "dmarc": dmarc or "unknown",
        }
    )

    suspicious_sender_signals = email.get("suspicious_sender_signals")
    if isinstance(suspicious_sender_signals, str):
        try:
            import json

            suspicious_sender_signals = json.loads(suspicious_sender_signals)
        except Exception:
            suspicious_sender_signals = None

    if suspicious_sender_signals is None:
        suspicious = _sender_suspicion_signals(email)
        suspicious_sender_signals = {
            "reply_to_differs": suspicious["reply_to_differs"],
            "display_name_mismatch": suspicious["display_name_mismatch"],
            "punycode_domain": suspicious["punycode_domain"],
        }
        is_suspicious_sender = suspicious["is_suspicious_sender"]
    else:
        is_suspicious_sender = bool(email.get("is_suspicious_sender"))

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
        "spf": auth["spf"],
        "dkim": auth["dkim"],
        "dmarc": auth["dmarc"],
        "auth_results_raw": auth["auth_results_raw"],
        "is_suspicious_sender": is_suspicious_sender,
        "suspicious_sender_signals": suspicious_sender_signals,
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
        get_template_context(
            request,
            signals=signals,
            priority=priority,
            priority_reason=priority_reason,
            related_emails=related,
            suggested_actions=suggested_actions,
            has_embeddings=db.has_embeddings(),
            folder=folder,
            uid=uid,
        ),
    )
