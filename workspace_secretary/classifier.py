"""Email classification engine with multi-stage classification."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class EmailCategory(str, Enum):
    ACTION_REQUIRED = "action-required"
    FYI = "fyi"
    NEWSLETTER = "newsletter"
    NOTIFICATION = "notification"
    CLEANUP = "cleanup"
    UNCLEAR = "unclear"


CATEGORY_LABELS: dict[EmailCategory, str | None] = {
    EmailCategory.ACTION_REQUIRED: "Secretary/Action-Required",
    EmailCategory.FYI: "Secretary/FYI",
    EmailCategory.NEWSLETTER: "Secretary/Newsletter",
    EmailCategory.NOTIFICATION: "Secretary/Notification",
    EmailCategory.CLEANUP: "Secretary/Auto-Cleaned",
    EmailCategory.UNCLEAR: None,
}

CATEGORY_ACTIONS: dict[EmailCategory, list[str]] = {
    EmailCategory.ACTION_REQUIRED: [],
    EmailCategory.FYI: ["mark_read"],
    EmailCategory.NEWSLETTER: ["mark_read", "archive"],
    EmailCategory.NOTIFICATION: ["mark_read"],
    EmailCategory.CLEANUP: ["mark_read", "archive"],
    EmailCategory.UNCLEAR: [],
}


@dataclass
class Classification:
    uid: int
    category: EmailCategory
    confidence: float
    reasoning: str
    label: str | None = None
    actions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.label is None:
            self.label = CATEGORY_LABELS.get(self.category)
        if not self.actions:
            self.actions = CATEGORY_ACTIONS.get(self.category, [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "category": self.category.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "label": self.label,
            "actions": self.actions,
        }


@dataclass
class TriageResult:
    total_processed: int
    by_category: dict[str, list[Classification]]
    high_confidence: list[Classification]
    needs_review: list[Classification]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "summary": {cat: len(items) for cat, items in self.by_category.items()},
            "high_confidence_count": len(self.high_confidence),
            "needs_review_count": len(self.needs_review),
            "by_category": {
                cat: [c.to_dict() for c in items]
                for cat, items in self.by_category.items()
            },
            "high_confidence": [c.to_dict() for c in self.high_confidence],
            "needs_review": [c.to_dict() for c in self.needs_review],
        }


def classify_email_fast(
    email: dict[str, Any], signals: dict[str, Any], user_email: str
) -> Classification | None:
    """Stage 1: Fast pattern-based classification for high-confidence cases."""
    uid = email.get("uid", 0)

    if signals.get("is_newsletter") and signals.get("newsletter_confidence", 0) > 0.7:
        return Classification(
            uid=uid,
            category=EmailCategory.NEWSLETTER,
            confidence=min(0.95, signals["newsletter_confidence"] + 0.2),
            reasoning="Unsubscribe link + newsletter sender pattern",
        )

    if signals.get("notification_type"):
        return Classification(
            uid=uid,
            category=EmailCategory.NOTIFICATION,
            confidence=0.92,
            reasoning=f"Known notification service: {signals['notification_type']}",
        )

    user_in_to = signals.get("user_in_to", False)
    user_in_cc = signals.get("user_in_cc", False)
    user_mentioned = signals.get("mentions_my_name", False)

    if not user_in_to and not user_in_cc and not user_mentioned:
        return Classification(
            uid=uid,
            category=EmailCategory.CLEANUP,
            confidence=0.90,
            reasoning="Not addressed to you, name not mentioned",
        )

    return None


def classify_email_signals(
    email: dict[str, Any], signals: dict[str, Any], user_email: str
) -> Classification:
    """Stage 2: Signal-based scoring for medium confidence cases."""
    uid = email.get("uid", 0)

    if signals.get("is_from_vip"):
        if signals.get("is_addressed_to_me"):
            has_urgency = signals.get("has_question") or signals.get(
                "mentions_deadline"
            )
            return Classification(
                uid=uid,
                category=EmailCategory.ACTION_REQUIRED,
                confidence=0.92 if has_urgency else 0.85,
                reasoning="VIP sender with direct question/deadline"
                if has_urgency
                else "VIP sender addressing you directly",
            )

    if signals.get("is_addressed_to_me") and signals.get("has_question"):
        confidence = 0.88 if signals.get("mentions_deadline") else 0.80
        reasoning = "Question directed at you"
        if signals.get("mentions_deadline"):
            reasoning += " with deadline"
        return Classification(
            uid=uid,
            category=EmailCategory.ACTION_REQUIRED,
            confidence=confidence,
            reasoning=reasoning,
        )

    if signals.get("is_bulk_cc"):
        return Classification(
            uid=uid,
            category=EmailCategory.FYI,
            confidence=0.75,
            reasoning=f"You're in CC with {signals.get('recipient_count', 'many')} recipients",
        )

    user_in_cc = signals.get("user_in_cc", False)
    user_in_to = signals.get("user_in_to", False)
    if user_in_cc and not user_in_to:
        return Classification(
            uid=uid,
            category=EmailCategory.FYI,
            confidence=0.65,
            reasoning="You're in CC, not primary recipient",
        )

    return Classification(
        uid=uid,
        category=EmailCategory.UNCLEAR,
        confidence=0.40,
        reasoning="Requires deeper analysis",
    )


LLM_CLASSIFICATION_PROMPT = """You are an email triage assistant for {user_name} ({user_email}).

Classify each email into ONE category:
- action-required: User MUST respond, answer a question, complete a task, or make a decision
- fyi: Informational only - status updates, CC'd emails, announcements, no action needed
- newsletter: Marketing emails, digests, periodic updates (usually has unsubscribe link)
- notification: Automated system alerts - Zoom, GitHub, Google Docs, calendar, CI/CD, monitoring
- cleanup: Safe to archive - not addressed to user, irrelevant, spam-like

VIP senders (prioritize as action-required if they need something): {vip_list}

Respond with a JSON array. For each email:
{{"uid": <number>, "category": "<category>", "confidence": <0.0-1.0>, "reasoning": "<10 words max>"}}

Emails:
{emails_json}

JSON array only, no other text:"""


async def classify_emails_llm(
    emails: list[dict[str, Any]],
    llm_client: BaseChatModel,
    user_email: str,
    user_name: str,
    vip_senders: list[str],
    batch_size: int = 30,
) -> list[Classification]:
    """Stage 3: LLM classification for unclear emails, batched for efficiency."""
    if not emails:
        return []

    all_classifications: list[Classification] = []

    for i in range(0, len(emails), batch_size):
        batch = emails[i : i + batch_size]
        email_summaries = [
            {
                "uid": e.get("uid"),
                "from": e.get("from_addr", "")[:100],
                "to": e.get("to_addr", "")[:100],
                "cc": (e.get("cc_addr") or "")[:50],
                "subject": (e.get("subject") or "")[:150],
                "preview": (e.get("body_text") or "")[:400],
            }
            for e in batch
        ]

        prompt = LLM_CLASSIFICATION_PROMPT.format(
            user_name=user_name,
            user_email=user_email,
            vip_list=", ".join(vip_senders) if vip_senders else "none configured",
            emails_json=json.dumps(email_summaries, indent=2),
        )

        try:
            response = await llm_client.ainvoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            if not isinstance(content, str):
                content = str(content)

            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                results = json.loads(json_match.group())
            else:
                results = json.loads(content)

            for r in results:
                try:
                    category = EmailCategory(r["category"])
                    all_classifications.append(
                        Classification(
                            uid=r["uid"],
                            category=category,
                            confidence=float(r.get("confidence", 0.7)),
                            reasoning=r.get("reasoning", "LLM classified"),
                        )
                    )
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Invalid classification for uid {r.get('uid')}: {e}"
                    )
                    all_classifications.append(
                        Classification(
                            uid=r.get("uid", 0),
                            category=EmailCategory.UNCLEAR,
                            confidence=0.30,
                            reasoning=f"Parse error: {e}",
                        )
                    )

        except Exception as e:
            logger.error(f"LLM classification batch failed: {e}")
            for email in batch:
                all_classifications.append(
                    Classification(
                        uid=email.get("uid", 0),
                        category=EmailCategory.UNCLEAR,
                        confidence=0.30,
                        reasoning=f"LLM error: {str(e)[:50]}",
                    )
                )

    return all_classifications


async def triage_emails(
    emails: list[dict[str, Any]],
    llm_client: BaseChatModel | None,
    user_email: str,
    user_name: str,
    vip_senders: list[str],
) -> TriageResult:
    """Full triage pipeline: Pattern -> Signals -> LLM."""
    from workspace_secretary.signals import analyze_extended_signals

    all_classifications: list[Classification] = []
    unclear_emails: list[dict[str, Any]] = []

    for email in emails:
        signals = analyze_extended_signals(email, user_email, user_name, vip_senders)

        classification = classify_email_fast(email, signals, user_email)

        if classification is None:
            classification = classify_email_signals(email, signals, user_email)

        if classification.category == EmailCategory.UNCLEAR:
            unclear_emails.append(email)
        else:
            all_classifications.append(classification)

    if unclear_emails and llm_client:
        logger.info(
            f"Sending {len(unclear_emails)} unclear emails to LLM for classification"
        )
        llm_classifications = await classify_emails_llm(
            unclear_emails, llm_client, user_email, user_name, vip_senders
        )
        all_classifications.extend(llm_classifications)

    by_category: dict[str, list[Classification]] = {}
    high_confidence: list[Classification] = []
    needs_review: list[Classification] = []

    for c in all_classifications:
        cat_key = c.category.value
        if cat_key not in by_category:
            by_category[cat_key] = []
        by_category[cat_key].append(c)

        if c.confidence >= 0.90:
            high_confidence.append(c)
        else:
            needs_review.append(c)

    return TriageResult(
        total_processed=len(emails),
        by_category=by_category,
        high_confidence=high_confidence,
        needs_review=needs_review,
    )
