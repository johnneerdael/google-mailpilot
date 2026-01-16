"""Shared email signal analysis for UI and MCP tools.

This module provides a single source of truth for email signal analysis,
ensuring consistency between the web UI and LangGraph assistant tools.
"""

import re
from typing import Any, Protocol


# =============================================================================
# Newsletter Detection Patterns
# =============================================================================

NEWSLETTER_BODY_PATTERNS = [
    r"unsubscribe",
    r"view\s+(in|this|email\s+in)\s+browser",
    r"email\s+preferences",
    r"opt[\s-]?out",
    r"manage\s+(your\s+)?(subscription|preferences)",
    r"update\s+your\s+preferences",
    r"privacy\s+policy",
    r"©\s*\d{4}",  # Copyright footer
    r"click\s+here\s+to\s+unsubscribe",
    r"no\s+longer\s+wish\s+to\s+receive",
]

NEWSLETTER_SENDER_PATTERNS = [
    r"newsletter@",
    r"digest@",
    r"updates?@",
    r"news@",
    r"marketing@",
    r"campaigns?@",
    r"announcements?@",
    r"weekly@",
    r"daily@",
    r"monthly@",
    r"bulletin@",
    r"communications?@",
    r"info@",
    r"hello@",
]

AUTOMATED_SENDER_PATTERNS = [
    r"no[-_]?reply@",
    r"noreply@",
    r"donotreply@",
    r"do-not-reply@",
    r"notifications?@",
    r"alerts?@",
    r"mailer[-_]?daemon@",
    r"postmaster@",
    r"auto[-_]?",
    r"system@",
    r"bot@",
    r"automated@",
    r"service@",
    r"support@.*\.com$",  # Generic support addresses
]

# Known notification service domains mapped to category
KNOWN_NOTIFICATION_DOMAINS: dict[str, str] = {
    # Collaboration & Meetings
    "zoom.us": "meeting",
    "zoomgov.com": "meeting",
    "docs.google.com": "document",
    "drive.google.com": "document",
    "calendar.google.com": "calendar",
    "meet.google.com": "meeting",
    "teams.microsoft.com": "meeting",
    "sharepoint.com": "document",
    "onedrive.com": "document",
    # Dev tools
    "github.com": "code",
    "gitlab.com": "code",
    "bitbucket.org": "code",
    "jira.atlassian.com": "project",
    "atlassian.com": "project",
    "confluence.atlassian.com": "document",
    "linear.app": "project",
    "asana.com": "project",
    "trello.com": "project",
    "monday.com": "project",
    "notion.so": "document",
    # Security & SSO
    "okta.com": "security",
    "onelogin.com": "security",
    "auth0.com": "security",
    "duo.com": "security",
    # IT Service Management
    "servicenow.com": "ticket",
    "zendesk.com": "ticket",
    "freshdesk.com": "ticket",
    "intercom.io": "ticket",
    # CRM & Sales
    "salesforce.com": "crm",
    "hubspot.com": "crm",
    "pipedrive.com": "crm",
    # Chat & Communication
    "slack.com": "chat",
    "discord.com": "chat",
    # Monitoring & Alerts
    "pagerduty.com": "alert",
    "opsgenie.com": "alert",
    "datadog.com": "monitoring",
    "sentry.io": "error",
    "newrelic.com": "monitoring",
    "splunk.com": "monitoring",
    # CI/CD
    "circleci.com": "ci",
    "travis-ci.com": "ci",
    "jenkins.io": "ci",
    "buildkite.com": "ci",
    # Cloud providers
    "aws.amazon.com": "cloud",
    "cloud.google.com": "cloud",
    "azure.microsoft.com": "cloud",
}


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


def _extract_domain(email_addr: str) -> str:
    """Extract domain from email address, handling display names."""
    match = re.search(r"@([\w.-]+)", email_addr.lower())
    return match.group(1) if match else ""


def analyze_extended_signals(
    email: dict[str, Any],
    user_email: str,
    user_name: str,
    vip_senders: list[str],
) -> dict[str, Any]:
    """Enhanced signal detection including newsletter/notification patterns.

    Extends base analyze_signals with:
    - is_newsletter: Email has unsubscribe patterns
    - is_automated_sender: From no-reply/automated address
    - notification_type: Type if from known service (meeting, code, etc)
    - newsletter_confidence: 0.0-1.0 score
    - is_bulk_cc: User in CC with >5 recipients
    - recipient_count: Total recipients
    - user_in_to: User is in To field
    - user_in_cc: User is in CC field
    """
    name_parts = user_name.split() if user_name else []
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[-1] if len(name_parts) > 1 else ""

    class SimpleIdentity:
        def matches_email(self, address: str) -> bool:
            return user_email.lower() in address.lower()

        def matches_name_part(self, text: str) -> bool:
            text_lower = text.lower()
            if first_name and first_name.lower() in text_lower:
                return True
            if last_name and last_name.lower() in text_lower:
                return True
            return False

        @property
        def full_name(self) -> str | None:
            return user_name

    base_signals = analyze_signals(email, user_email, SimpleIdentity(), vip_senders)

    from_addr = (email.get("from_addr") or "").lower()
    body = (email.get("body_text") or email.get("body_html") or "")[:1500].lower()
    to_addr = (email.get("to_addr") or "").lower()
    cc_addr = (email.get("cc_addr") or "").lower()

    newsletter_body_matches = sum(
        1 for p in NEWSLETTER_BODY_PATTERNS if re.search(p, body, re.I)
    )
    newsletter_sender_match = any(
        re.search(p, from_addr) for p in NEWSLETTER_SENDER_PATTERNS
    )
    automated_sender_match = any(
        re.search(p, from_addr) for p in AUTOMATED_SENDER_PATTERNS
    )

    newsletter_confidence = min(
        1.0,
        (newsletter_body_matches * 0.15)
        + (0.35 if newsletter_sender_match else 0)
        + (0.25 if automated_sender_match else 0),
    )

    sender_domain = _extract_domain(from_addr)
    notification_type = KNOWN_NOTIFICATION_DOMAINS.get(sender_domain)

    all_recipients = f"{to_addr},{cc_addr}"
    recipient_emails = [r.strip() for r in all_recipients.split(",") if "@" in r]
    recipient_count = len(recipient_emails)

    user_in_to = user_email.lower() in to_addr
    user_in_cc = user_email.lower() in cc_addr
    is_bulk_cc = user_in_cc and not user_in_to and recipient_count > 5

    return {
        **base_signals,
        "is_newsletter": newsletter_confidence > 0.5,
        "is_automated_sender": automated_sender_match,
        "notification_type": notification_type,
        "newsletter_confidence": newsletter_confidence,
        "is_bulk_cc": is_bulk_cc,
        "recipient_count": recipient_count,
        "user_in_to": user_in_to,
        "user_in_cc": user_in_cc,
    }
