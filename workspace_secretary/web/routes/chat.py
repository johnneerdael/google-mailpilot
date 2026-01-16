"""Chat routes for AI assistant using LangGraph.

Provides streaming chat with HITL (Human-in-the-Loop) for mutation operations.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session
from workspace_secretary.web.database import get_db
from workspace_secretary.engine_client import EngineClient
from workspace_secretary.web.engine_client import get_engine_url
from workspace_secretary.assistant import (
    create_assistant_graph,
    get_graph,
    AssistantContext,
    CONVERSATION_STARTERS,
    get_starters,
)
from workspace_secretary.assistant.state import create_initial_state, AssistantState
from workspace_secretary.assistant.graph import (
    stream_graph,
    invoke_graph,
    get_pending_mutation,
    reject_mutation,
)
from workspace_secretary.assistant.streaming import (
    format_sse_events,
    format_error_sse,
    format_interrupt_sse,
    extract_final_response,
)
from workspace_secretary.assistant.tool_registry import is_mutation_tool
from workspace_secretary.config import ServerConfig

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# Cache for initialized graph
_graph_initialized = False


def _ensure_graph_initialized(config: ServerConfig) -> None:
    """Ensure the assistant graph is initialized with context."""
    global _graph_initialized
    if not _graph_initialized:
        context = AssistantContext.from_config(
            db=get_db(),
            engine=EngineClient(api_url=get_engine_url()),
            config=config,
        )
        create_assistant_graph(context)
        _graph_initialized = True


def _get_thread_id(session: Session) -> str:
    """Get thread ID for a user session."""
    return f"chat-{session.user_id}"


def _create_state_from_session(
    session: Session,
    config: ServerConfig,
) -> AssistantState:
    """Create initial state from session and config."""
    return create_initial_state(
        user_id=session.user_id,
        user_email=session.email or config.identity.email,
        user_name=session.name or config.identity.full_name or "User",
        timezone=config.timezone,
        working_hours={
            "start": config.working_hours.start,
            "end": config.working_hours.end,
            "workdays": config.working_hours.workdays,
        },
        selected_calendar_ids=["primary"],
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, session: Session = Depends(require_auth)):
    """Render the chat page."""
    ctx = get_template_context(
        request,
        page="chat",
        chat_session_id=session.user_id,
        conversation_starters=get_starters(),
    )
    return templates.TemplateResponse("chat.html", ctx)


@router.post("/api/chat")
async def chat_message(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Handle non-streaming chat message (fallback)."""
    from workspace_secretary.web import get_web_config
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"error": "Server configuration not available"}

    _ensure_graph_initialized(config)

    form = await request.form()
    message = str(form.get("message", "")).strip()

    if not message:
        return {"error": "Empty message"}

    thread_id = _get_thread_id(session)
    state = _create_state_from_session(session, config)

    # Add user message
    state["messages"] = [HumanMessage(content=message)]

    try:
        result = await invoke_graph(state, thread_id)
        response = extract_final_response(result)
        return {"response": response}
    except Exception as e:
        logger.exception(f"Chat error: {e}")
        return {"error": str(e)}


@router.post("/api/chat/stream")
async def chat_message_stream(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Handle streaming chat message with HITL support."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:

        async def error_gen():
            yield format_error_sse("Server configuration not available")

        return StreamingResponse(error_gen(), media_type="text/event-stream")

    _ensure_graph_initialized(config)

    form = await request.form()
    message = str(form.get("message", "")).strip()

    if not message:

        async def error_gen():
            yield format_error_sse("Empty message")

        return StreamingResponse(error_gen(), media_type="text/event-stream")

    thread_id = _get_thread_id(session)
    state = _create_state_from_session(session, config)

    # Add user message
    state["messages"] = [HumanMessage(content=message)]

    async def generate():
        try:
            async for event in stream_graph(state, thread_id):
                event_type = event.get("event", "")

                # Stream tokens
                if event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    content = getattr(chunk, "content", "")
                    if content:
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                # Tool execution events
                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    output = event.get("data", {}).get("output", "")
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': str(output)[:500]})}\n\n"

                # Graph completion or interrupt
                elif event_type == "on_chain_end":
                    if event.get("name") == "LangGraph":
                        # Check if we're interrupted for HITL
                        pending = get_pending_mutation(thread_id)
                        if pending:
                            yield format_interrupt_sse(
                                pending["name"],
                                pending.get("args", {}),
                            )
                        else:
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.exception(f"Stream error: {e}")
            yield format_error_sse(str(e))
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/chat/approve")
async def approve_mutation(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Approve a pending mutation and resume execution."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"error": "Server configuration not available"}

    _ensure_graph_initialized(config)

    thread_id = _get_thread_id(session)

    # Check there's a pending mutation
    pending = get_pending_mutation(thread_id)
    if not pending:
        return {"error": "No pending mutation to approve"}

    async def generate():
        try:
            # Resume from interrupt
            async for event in stream_graph(None, thread_id, resume=True):
                event_type = event.get("event", "")

                if event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    content = getattr(chunk, "content", "")
                    if content:
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    output = event.get("data", {}).get("output", "")
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': str(output)[:500]})}\n\n"

                elif event_type == "on_chain_end":
                    if event.get("name") == "LangGraph":
                        # Check for another interrupt
                        pending = get_pending_mutation(thread_id)
                        if pending:
                            yield format_interrupt_sse(
                                pending["name"],
                                pending.get("args", {}),
                            )
                        else:
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.exception(f"Approval stream error: {e}")
            yield format_error_sse(str(e))
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/chat/reject")
async def reject_mutation_endpoint(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Reject a pending mutation."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"error": "Server configuration not available"}

    _ensure_graph_initialized(config)

    thread_id = _get_thread_id(session)

    # Check there's a pending mutation
    pending = get_pending_mutation(thread_id)
    if not pending:
        return {"error": "No pending mutation to reject"}

    form = await request.form()
    reason = str(form.get("reason", "User declined")).strip()

    # Reject and get updated state
    reject_mutation(thread_id, reason)

    return {
        "status": "rejected",
        "tool": pending["name"],
        "message": f"Action '{pending['name']}' was rejected: {reason}",
    }


@router.post("/api/chat/clear")
async def clear_chat(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Clear chat history for the user."""
    # With LangGraph and PostgresSaver, we don't have an explicit clear
    # The thread_id ensures isolation, and history persists
    # For now, we could create a new thread or just acknowledge
    return {"status": "cleared", "message": "Start a new conversation"}


@router.get("/api/chat/history")
async def get_chat_history(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Get chat history from checkpointer."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"messages": []}

    try:
        _ensure_graph_initialized(config)
        graph = get_graph()

        thread_id = _get_thread_id(session)
        state = graph.get_state({"configurable": {"thread_id": thread_id}})

        if not state or not state.values:
            return {"messages": []}

        messages = []
        for msg in state.values.get("messages", []):
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": msg.content})

        return {"messages": messages}

    except Exception as e:
        logger.exception(f"Error getting chat history: {e}")
        return {"messages": []}


@router.get("/api/chat/pending")
async def get_pending_action(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Check if there's a pending mutation awaiting approval."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"pending": None}

    try:
        _ensure_graph_initialized(config)
        thread_id = _get_thread_id(session)

        pending = get_pending_mutation(thread_id)
        if pending:
            return {
                "pending": {
                    "tool": pending["name"],
                    "args": pending.get("args", {}),
                }
            }
        return {"pending": None}

    except Exception as e:
        logger.exception(f"Error checking pending: {e}")
        return {"pending": None}


@router.get("/api/chat/starters")
async def get_conversation_starters(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Get conversation starter suggestions."""
    return {"starters": get_starters()}
