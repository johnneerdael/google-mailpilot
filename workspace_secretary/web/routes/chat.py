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
    format_batch_progress_sse,
    format_batch_complete_sse,
    extract_final_response,
)
from workspace_secretary.assistant.tool_registry import is_mutation_tool, is_batch_tool
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
                    # Handle Gemini format: [{'type': 'text', 'text': '...'}]
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text", "")
                                if text:
                                    yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                    elif content:
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
                    # Handle Gemini format: [{'type': 'text', 'text': '...'}]
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text", "")
                                if text:
                                    yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                    elif content:
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


@router.get("/api/chat/greeting")
async def get_dynamic_greeting(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Generate a dynamic, personalized greeting using the configured LLM."""
    from workspace_secretary.web.routes.analysis import get_config
    from workspace_secretary.web.llm_client import get_llm_client
    import hashlib
    from datetime import datetime
    import random

    session_id = request.query_params.get("session_id", "")
    config = get_config()

    hour = datetime.now().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    user_name = "there"
    if config and config.identity:
        user_name = (
            config.identity.full_name or config.identity.email.split("@")[0] or "there"
        )
        first_name = user_name.split()[0] if user_name else "there"
    else:
        first_name = "there"

    fallback_greetings = [
        f"Hey {first_name}, ready to tackle your inbox together!",
        f"Good {time_of_day} {first_name}! Your email co-pilot is standing by.",
        f"Hi {first_name}! Let's see what's waiting in your inbox.",
        f"Welcome back {first_name}! Ready to sort through those emails?",
        f"{first_name}, your inbox awaits! Where shall we start?",
        f"Good {time_of_day}! Let me help you stay on top of your emails.",
    ]

    if not config:
        return {"greeting": random.choice(fallback_greetings)}

    try:
        client = get_llm_client()
        if not client or not client.is_configured:
            return {"greeting": random.choice(fallback_greetings)}

        session_seed = hashlib.md5(session_id.encode()).hexdigest()[:8]

        prompt = f"""Generate ONE friendly greeting (8-15 words) from Piper (an email assistant) to {first_name} this {time_of_day}.

Style: warm, helpful, slightly playful. Mention inbox or emails.
Seed for variety: {session_seed}

Examples:
- "Hey {first_name}, ready to sort through your inbox together?"
- "Good {time_of_day} {first_name}! Your emails await, let's dive in!"

Output ONLY the greeting text, no quotes, no explanation."""

        greeting = await client.generate_simple(prompt, max_tokens=50)

        if greeting and len(greeting.strip()) > 25:
            greeting = greeting.strip().strip('"').strip("'")
            if len(greeting) > 80:
                greeting = greeting[:80].rsplit(" ", 1)[0] + "..."
            return {"greeting": greeting}

    except Exception as e:
        logger.warning(f"Greeting generation failed: {e}")

    return {"greeting": random.choice(fallback_greetings)}


@router.post("/api/chat/batch/cancel")
async def cancel_batch(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Cancel an ongoing batch operation."""
    from workspace_secretary.web.routes.analysis import get_config

    config = get_config()
    if not config:
        return {"error": "Server configuration not available"}

    _ensure_graph_initialized(config)
    thread_id = _get_thread_id(session)

    try:
        graph = get_graph()
        state = graph.get_state({"configurable": {"thread_id": thread_id}})

        if state and state.values.get("batch_status") == "running":
            graph.update_state(
                {"configurable": {"thread_id": thread_id}},
                {"batch_cancel_requested": True},
            )
            return {"status": "cancelling", "message": "Batch cancellation requested"}

        return {"status": "no_batch", "message": "No active batch operation"}
    except Exception as e:
        logger.exception(f"Error cancelling batch: {e}")
        return {"error": str(e)}


@router.post("/api/chat/batch/approve")
async def approve_batch(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Approve batch operation results and execute."""
    from workspace_secretary.web.routes.analysis import get_config
    from workspace_secretary.assistant.tools_mutation import (
        execute_clean_batch,
        process_email,
    )
    from workspace_secretary.assistant.context import get_context

    config = get_config()
    if not config:
        return {"error": "Server configuration not available"}

    _ensure_graph_initialized(config)

    form = await request.form()
    approved_uids_json = str(form.get("uids", "[]"))
    action = str(form.get("action", "archive"))
    source_folder = str(form.get("folder", "INBOX"))

    try:
        approved_uids = json.loads(approved_uids_json) if approved_uids_json else []
    except json.JSONDecodeError:
        return {"error": "Invalid UIDs format"}

    if not approved_uids:
        return {"error": "No items selected for approval"}

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'batch_execute_start', 'count': len(approved_uids)})}\n\n"

            ctx = get_context()
            success_count = 0
            error_count = 0

            for uid in approved_uids:
                try:
                    if action == "archive":
                        ctx.engine.move_email(
                            uid, source_folder, "Secretary/Auto-Cleaned"
                        )
                        ctx.engine.mark_read(uid, "Secretary/Auto-Cleaned")
                    elif action == "mark_read":
                        ctx.engine.mark_read(uid, source_folder)
                    elif action == "delete":
                        ctx.engine.move_email(uid, source_folder, "[Gmail]/Trash")
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Failed to process email {uid}: {e}")

                if (success_count + error_count) % 10 == 0:
                    yield f"data: {json.dumps({'type': 'batch_execute_progress', 'processed': success_count + error_count, 'total': len(approved_uids)})}\n\n"

            yield f"data: {json.dumps({'type': 'batch_execute_complete', 'success': success_count, 'errors': error_count})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.exception(f"Batch execute error: {e}")
            yield format_error_sse(str(e))
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def group_items_by_confidence(items: list[dict]) -> dict[str, list[dict]]:
    """Group batch items by confidence level for tiered approval."""
    grouped = {"high": [], "medium": [], "low": []}
    for item in items:
        confidence = item.get("confidence", "medium")
        if confidence in grouped:
            grouped[confidence].append(item)
        else:
            grouped["medium"].append(item)
    return grouped
