"""State schema for the LangGraph assistant.

Defines the TypedDict state that flows through the graph nodes.
"""

from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages


from typing import Literal

BatchStatus = Literal["idle", "running", "awaiting_approval", "complete", "cancelled"]


class AssistantState(TypedDict):
    """State schema for the assistant graph."""

    messages: Annotated[list, add_messages]

    user_id: str
    user_email: str
    user_name: str

    timezone: str
    working_hours: dict[str, Any]
    selected_calendar_ids: list[str]

    pending_mutation: Optional[dict[str, Any]]
    continuation_state: Optional[str]
    tool_error: Optional[str]

    batch_status: BatchStatus
    batch_tool: Optional[str]
    batch_args: Optional[dict[str, Any]]
    batch_continuation_state: Optional[str]
    batch_items: list[dict[str, Any]]
    batch_processed_count: int
    batch_total_estimate: int
    batch_cancel_requested: bool


def create_initial_state(
    user_id: str,
    user_email: str,
    user_name: str,
    timezone: str = "UTC",
    working_hours: Optional[dict[str, Any]] = None,
    selected_calendar_ids: Optional[list[str]] = None,
) -> AssistantState:
    """Create initial state for a new conversation.

    Args:
        user_id: Unique user identifier
        user_email: User's email address
        user_name: User's display name
        timezone: IANA timezone string
        working_hours: Working hours config dict
        selected_calendar_ids: Calendar IDs to query

    Returns:
        Initial AssistantState with empty messages
    """
    return AssistantState(
        messages=[],
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        timezone=timezone,
        working_hours=working_hours or {"start": "09:00", "end": "17:00"},
        selected_calendar_ids=selected_calendar_ids or ["primary"],
        pending_mutation=None,
        continuation_state=None,
        tool_error=None,
        batch_status="idle",
        batch_tool=None,
        batch_args=None,
        batch_continuation_state=None,
        batch_items=[],
        batch_processed_count=0,
        batch_total_estimate=0,
        batch_cancel_requested=False,
    )
