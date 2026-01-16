"""Triage tools for the LangGraph assistant.

Smart email classification using pattern matching, signals, and LLM.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from langchain_core.tools import tool

from workspace_secretary.assistant.context import get_context
from workspace_secretary.classifier import (
    CATEGORY_ACTIONS,
    CATEGORY_LABELS,
    EmailCategory,
    triage_emails,
)
from workspace_secretary.db.queries import emails as email_queries

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@tool
async def triage_inbox(
    folder: str = "INBOX",
    limit: int = 100,
    continuation_state: Optional[str] = None,
) -> str:
    """Intelligently triage inbox emails into categories.

    Uses pattern matching, signal analysis, and LLM classification to
    categorize emails into:
    - action-required: Direct questions/requests needing your response
    - fyi: CC'd emails, bulk, informational
    - newsletter: Marketing, digests with unsubscribe
    - notification: Zoom, GitHub, Google Docs, etc
    - cleanup: Safe to archive

    High confidence (>90%) items are auto-labeled without prompting.
    Medium/low confidence items require your approval.

    Args:
        folder: Email folder to triage (default: INBOX)
        limit: Max emails per batch (default: 100)
        continuation_state: State from previous call for pagination

    Returns:
        JSON with triage results grouped by category and confidence
    """
    ctx = get_context()

    offset = 0
    if continuation_state:
        try:
            state = json.loads(continuation_state)
            offset = state.get("offset", 0)
        except json.JSONDecodeError:
            pass

    emails = email_queries.get_inbox_emails(
        ctx.db,
        folder=folder,
        unread_only=True,
        limit=limit,
        offset=offset,
    )

    if not emails:
        return json.dumps(
            {
                "status": "complete",
                "message": "No unread emails to triage",
                "total_processed": 0,
            }
        )

    user_email = ctx.user_email
    user_name = ctx.user_name
    vip_senders = ctx.vip_senders

    from workspace_secretary.assistant.graph import create_llm

    llm_client = create_llm(ctx.config)

    result = await triage_emails(
        emails=emails,
        llm_client=llm_client,
        user_email=user_email,
        user_name=user_name,
        vip_senders=vip_senders,
    )

    total_unread = email_queries.count_emails(ctx.db, folder)
    has_more = (offset + len(emails)) < total_unread

    return json.dumps(
        {
            "status": "partial" if has_more else "complete",
            "has_more": has_more,
            "continuation_state": json.dumps({"offset": offset + len(emails)})
            if has_more
            else None,
            **result.to_dict(),
        }
    )


@tool
def apply_triage_labels(
    classifications_json: str,
    auto_apply_high_confidence: bool = True,
) -> str:
    """Apply labels and actions from triage results.

    For high-confidence (>90%) classifications:
    - Auto-applies labels
    - Marks read if specified in actions
    - Archives if specified in actions

    For lower confidence, applies labels but skips destructive actions
    unless explicitly approved.

    Args:
        classifications_json: JSON array of classification results from triage_inbox
        auto_apply_high_confidence: If True, auto-apply all high confidence actions

    Returns:
        JSON with results of label application
    """
    ctx = get_context()

    try:
        items = json.loads(classifications_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid classifications JSON"})

    results = {
        "labels_applied": 0,
        "marked_read": 0,
        "archived": 0,
        "errors": [],
    }

    for item in items:
        uid = item.get("uid")
        label = item.get("label")
        actions = item.get("actions", [])
        confidence = item.get("confidence", 0)

        if not uid:
            continue

        try:
            if label:
                try:
                    ctx.engine.modify_labels(uid, "INBOX", [label], action="add")
                    results["labels_applied"] += 1
                except Exception as e:
                    logger.warning(f"Failed to apply label {label} to {uid}: {e}")
                    results["errors"].append(
                        {"uid": uid, "error": f"Label failed: {e}"}
                    )

            if confidence >= 0.90 and auto_apply_high_confidence:
                if "mark_read" in actions:
                    try:
                        ctx.engine.mark_read(uid, "INBOX")
                        email_queries.mark_email_read(
                            ctx.db, uid, "INBOX", is_read=True
                        )
                        results["marked_read"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to mark {uid} as read: {e}")

                if "archive" in actions:
                    try:
                        ctx.engine.move_email(uid, "INBOX", "[Gmail]/All Mail")
                        email_queries.delete_email(ctx.db, uid, "INBOX")
                        results["archived"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to archive {uid}: {e}")

        except Exception as e:
            results["errors"].append({"uid": uid, "error": str(e)})

    return json.dumps(results)


@tool
def get_triage_summary(classifications_json: str) -> str:
    """Format triage results for user display.

    Takes raw triage results and formats them for human review,
    showing counts by category and sample emails.

    Args:
        classifications_json: JSON with triage results from triage_inbox

    Returns:
        Formatted markdown summary for display
    """
    try:
        data = json.loads(classifications_json)
    except json.JSONDecodeError:
        return "Error: Invalid triage data"

    lines = [f"## Inbox Triage Results\n"]
    lines.append(f"**Total processed:** {data.get('total_processed', 0)} emails\n")

    summary = data.get("summary", {})
    high_conf_count = data.get("high_confidence_count", 0)
    review_count = data.get("needs_review_count", 0)

    lines.append(f"**High confidence (auto-apply):** {high_conf_count}")
    lines.append(f"**Needs review:** {review_count}\n")

    category_icons = {
        "action-required": "🔴",
        "fyi": "📋",
        "newsletter": "📰",
        "notification": "🔔",
        "cleanup": "🗑️",
        "unclear": "❓",
    }

    category_labels = {
        "action-required": "Action Required",
        "fyi": "FYI / Informational",
        "newsletter": "Newsletters",
        "notification": "Notifications",
        "cleanup": "Safe to Archive",
        "unclear": "Needs Review",
    }

    by_category = data.get("by_category", {})

    for cat_key in [
        "action-required",
        "fyi",
        "newsletter",
        "notification",
        "cleanup",
        "unclear",
    ]:
        items = by_category.get(cat_key, [])
        if not items:
            continue

        icon = category_icons.get(cat_key, "📧")
        label = category_labels.get(cat_key, cat_key)
        count = len(items)

        lines.append(f"\n### {icon} {label} ({count})")

        for item in items[:5]:
            uid = item.get("uid")
            reasoning = item.get("reasoning", "")
            confidence = item.get("confidence", 0)
            conf_pct = int(confidence * 100)
            lines.append(f"- UID {uid}: {reasoning} ({conf_pct}%)")

        if count > 5:
            lines.append(f"- ... and {count - 5} more")

    return "\n".join(lines)


TRIAGE_TOOLS = [triage_inbox, apply_triage_labels, get_triage_summary]
