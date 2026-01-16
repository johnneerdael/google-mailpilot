"""SSE event streaming utilities for the LangGraph assistant."""

import json
from typing import Any, AsyncIterator


async def format_sse_events(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[str]:
    """Format LangGraph events as Server-Sent Events."""
    async for event in events:
        event_type = event.get("event", "")

        if event_type == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk", {})
            content = chunk.get("content", "")
            if content:
                yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

        elif event_type == "on_tool_start":
            tool_name = event.get("name", "unknown")
            yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

        elif event_type == "on_tool_end":
            tool_name = event.get("name", "unknown")
            output = event.get("data", {}).get("output", "")
            yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': str(output)[:500]})}\n\n"

        elif event_type == "on_custom_event":
            custom_name = event.get("name", "")
            if custom_name == "batch_progress":
                data = event.get("data", {})
                yield f"data: {json.dumps({'type': 'batch_progress', **data})}\n\n"

        elif event_type == "on_chain_end":
            if event.get("name") == "LangGraph":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"


def format_error_sse(error: str) -> str:
    """Format an error as SSE event."""
    return f"data: {json.dumps({'type': 'error', 'message': error})}\n\n"


def format_interrupt_sse(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Format a HITL interrupt as SSE event."""
    return f"data: {json.dumps({'type': 'interrupt', 'tool': tool_name, 'args': tool_args})}\n\n"


def format_batch_progress_sse(
    tool_name: str,
    processed: int,
    total_estimate: int,
    items_found: int,
    has_more: bool,
) -> str:
    """Format batch progress as SSE event."""
    return f"data: {json.dumps({'type': 'batch_progress', 'tool': tool_name, 'processed': processed, 'total_estimate': total_estimate, 'items_found': items_found, 'has_more': has_more})}\n\n"


def format_batch_complete_sse(
    tool_name: str,
    total_items: int,
    processed: int,
    items: list[dict[str, Any]],
) -> str:
    """Format batch completion as SSE event with aggregated results."""
    return f"data: {json.dumps({'type': 'batch_complete', 'tool': tool_name, 'total_items': total_items, 'processed': processed, 'items': items})}\n\n"


def format_action_buttons_sse(
    buttons: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> str:
    payload = {
        "type": "action_buttons",
        "buttons": buttons,
    }
    if context:
        payload["context"] = context
    return f"data: {json.dumps(payload)}\n\n"


def format_triage_actions_sse(
    triage_result: dict[str, Any],
) -> str:
    """Format triage results with actionable buttons.

    Creates buttons for bulk actions on triaged emails based on category.

    Args:
        triage_result: Dict from triage_inbox with by_category, high_confidence_count, etc.

    Returns:
        SSE-formatted string with action_buttons event
    """
    buttons = []
    by_category = triage_result.get("by_category", {})

    high_conf_items = []
    for cat in ["newsletter", "notification", "cleanup"]:
        items = by_category.get(cat, [])
        high_conf_items.extend(
            [item for item in items if item.get("confidence", 0) >= 0.90]
        )

    if high_conf_items:
        uids = [item.get("uid") for item in high_conf_items if item.get("uid")]
        buttons.append(
            {
                "id": "apply_high_conf",
                "label": f"Apply labels & mark read ({len(uids)} emails)",
                "action": "apply_triage",
                "args": {"uids": uids, "apply_actions": True},
                "style": "primary",
                "icon": "✅",
            }
        )

    action_required = by_category.get("action-required", [])
    if action_required:
        uids = [item.get("uid") for item in action_required if item.get("uid")]
        buttons.append(
            {
                "id": "label_action_required",
                "label": f"Label as Action Required ({len(uids)})",
                "action": "apply_label",
                "args": {"uids": uids, "label": "Secretary/Action-Required"},
                "style": "secondary",
                "icon": "🔴",
            }
        )

    fyi_items = by_category.get("fyi", [])
    if fyi_items:
        uids = [item.get("uid") for item in fyi_items if item.get("uid")]
        buttons.append(
            {
                "id": "mark_fyi_read",
                "label": f"Mark FYI as read ({len(uids)})",
                "action": "mark_read",
                "args": {"uids": uids, "folder": "INBOX"},
                "style": "secondary",
                "icon": "📋",
            }
        )

    cleanup_items = by_category.get("cleanup", [])
    newsletter_items = by_category.get("newsletter", [])
    archivable = cleanup_items + newsletter_items
    if archivable:
        uids = [item.get("uid") for item in archivable if item.get("uid")]
        buttons.append(
            {
                "id": "archive_safe",
                "label": f"Archive ({len(uids)} newsletters/cleanup)",
                "action": "archive",
                "args": {
                    "uids": uids,
                    "folder": "INBOX",
                    "target": "Secretary/Auto-Cleaned",
                },
                "style": "secondary",
                "icon": "📦",
            }
        )

    context = {
        "summary": triage_result.get("summary", {}),
        "high_confidence_count": triage_result.get("high_confidence_count", 0),
        "needs_review_count": triage_result.get("needs_review_count", 0),
        "total_processed": triage_result.get("total_processed", 0),
    }

    return format_action_buttons_sse(buttons, context)


def extract_final_response(state: dict) -> str:
    """Extract the final assistant response from state."""
    messages = state.get("messages", [])

    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai":
            return msg.content
        elif isinstance(msg, dict) and msg.get("type") == "ai":
            return msg.get("content", "")
        elif hasattr(msg, "role") and msg.role == "assistant":
            return msg.content

    return "No response generated."
