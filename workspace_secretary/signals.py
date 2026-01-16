"""Shared email signal analysis for UI and MCP tools.

This module provides a single source of truth for email signal analysis,
ensuring consistency between the web UI and LangGraph assistant tools.
"""

import re
from typing import Any, Protocol


class IdentityProtocol(Protocol):
    """Protocol for identity matching."""

    def matches_email(self, address: str) -> bool:
        """Check if address matches user's email."""
        ...

    def matches_name_part(self, text: str) -> bool:
        """Check if user's name appears in text."""
        ...

    @property
    def full_name(self) -> str | None:
        """User's full name."""
        ...


def analyze_signals(
    email: dict[str, Any],
    user_email: str,
    identity: IdentityProtocol,
    vip_senders: list[str],
) -> dict[str, Any]:
    """Analyze email for actionable signals.

    Args:
        email: Email dict with from_addr, to_addr, cc_addr, body_text, subject, etc.
        user_email: Current user's email address
        identity: Identity object for name/email matching
        vip_senders: List of VIP sender email patterns

    Returns:
        Dict of signals:
        - is_from_vip: Sender matches a VIP pattern
        - is_addressed_to_me: User is in To: field
        - mentions_my_name: User's name appears in body
        - has_question: Email contains question markers
        - mentions_deadline: Email mentions urgency/deadlines
        - mentions_meeting: Email mentions scheduling/meetings
        - is_unread: Email is unread
        - is_important: Email marked important by provider
        - has_attachments: Email has attachments
    """
    from_addr = (email.get("from_addr") or "").lower()
    to_addr = (email.get("to_addr") or "").lower()
    subject = (email.get("subject") or "").lower()
    body = (email.get("body_text") or "").lower()
    text = subject + " " + body

    # VIP check
    is_from_vip = any(vip.lower() in from_addr for vip in vip_senders)

    # Addressed to user check - use identity matching for robustness
    is_addressed_to_me = False
    if to_addr:
        first_recipient = to_addr.split(",")[0].strip()
        is_addressed_to_me = identity.matches_email(first_recipient)

    # Name mentioned in body
    mentions_my_name = False
    if identity.full_name:
        mentions_my_name = identity.matches_name_part(body)

    # Question detection - expanded patterns
    question_patterns = [
        r"\?",
        r"\bcan you\b",
        r"\bcould you\b",
        r"\bwould you\b",
        r"\bplease\b",
        r"\bdo you\b",
        r"\bare you\b",
        r"\bwill you\b",
    ]
    has_question = any(re.search(p, text) for p in question_patterns)

    # Deadline/urgency detection
    deadline_patterns = [
        r"\beod\b",
        r"\basap\b",
        r"\burgent\b",
        r"\bdeadline\b",
        r"\bdue\b",
        r"\bby\s+(monday|tuesday|wednesday|thursday|friday|tomorrow|today)",
        r"\bend of day\b",
    ]
    mentions_deadline = any(re.search(p, text) for p in deadline_patterns)

    # Meeting/scheduling detection
    meeting_patterns = [
        r"\bmeet\b",
        r"\bmeeting\b",
        r"\bschedule\b",
        r"\bcalendar\b",
        r"\binvite\b",
        r"\bzoom\b",
        r"\bgoogle meet\b",
        r"\bteams\b",
        r"\bcall\b",
        r"\bvideo\b",
    ]
    mentions_meeting = any(re.search(p, text) for p in meeting_patterns)

    return {
        "is_from_vip": is_from_vip,
        "is_addressed_to_me": is_addressed_to_me,
        "mentions_my_name": mentions_my_name,
        "has_question": has_question,
        "mentions_deadline": mentions_deadline,
        "mentions_meeting": mentions_meeting,
        "is_unread": email.get("is_unread", False),
        "is_important": email.get("is_important", False),
        "has_attachments": email.get("has_attachments", False),
    }


def compute_priority(signals: dict[str, Any]) -> tuple[str, str]:
    """Compute priority level from signals.

    Args:
        signals: Dict of email signals

    Returns:
        Tuple of (priority_level, reason_string)
        - priority_level: "high", "medium", or "low"
        - reason_string: Human-readable explanation
    """
    score = 0
    reasons = []

    if signals.get("is_from_vip"):
        score += 3
        reasons.append("VIP sender")
    if signals.get("is_addressed_to_me"):
        score += 2
        reasons.append("Addressed to you")
    if signals.get("mentions_my_name"):
        score += 1
        reasons.append("Mentions your name")
    if signals.get("has_question"):
        score += 2
        reasons.append("Contains question")
    if signals.get("mentions_deadline"):
        score += 2
        reasons.append("Mentions deadline")
    if signals.get("is_important"):
        score += 1
        reasons.append("Marked important")

    if score >= 5:
        priority = "high"
    elif score >= 3:
        priority = "medium"
    else:
        priority = "low"

    return priority, ", ".join(reasons) if reasons else "No priority signals"


def format_signals_display(signals: dict[str, Any]) -> str:
    """Format signals for human-readable display.

    Args:
        signals: Dict of email signals

    Returns:
        Multi-line string with emoji indicators
    """
    lines = []
    if signals.get("is_from_vip"):
        lines.append("VIP sender")
    if signals.get("is_addressed_to_me"):
        lines.append("Directly addressed to you")
    if signals.get("mentions_my_name"):
        lines.append("Your name mentioned")
    if signals.get("has_question"):
        lines.append("Contains question")
    if signals.get("mentions_deadline"):
        lines.append("Mentions deadline/urgency")
    if signals.get("mentions_meeting"):
        lines.append("Mentions meeting/scheduling")
    if signals.get("has_attachments"):
        lines.append("Has attachments")
    if signals.get("is_important"):
        lines.append("Marked important")

    return "\n".join(lines) if lines else "No significant signals detected."
