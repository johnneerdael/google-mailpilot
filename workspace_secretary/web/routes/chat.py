"""Chat routes for AI assistant."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session
from workspace_secretary.web import database as db
from workspace_secretary.web import engine_client as engine
from workspace_secretary.web.llm_client import get_llm_client, ChatSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_chat_sessions: dict[str, ChatSession] = {}


def _get_or_create_session(session_id: str) -> ChatSession:
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = ChatSession()
    return _chat_sessions[session_id]


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, session: Session = Depends(require_auth)):
    ctx = get_template_context(
        request,
        page="chat",
        chat_session_id=session.user_id,
    )
    return templates.TemplateResponse("chat.html", ctx)


@router.post("/api/chat")
async def chat_message(
    request: Request,
    session: Session = Depends(require_auth),
):
    llm = get_llm_client()

    form = await request.form()
    message = str(form.get("message", "")).strip()

    if not message:
        return {"error": "Empty message"}

    llm.set_context(
        database=db,
        engine=engine,
        user_email=session.email or "user@example.com",
        user_name=session.name or "User",
    )

    chat_session = _get_or_create_session(session.user_id)
    response = await llm.chat(chat_session, message)

    return {"response": response}


@router.post("/api/chat/stream")
async def chat_message_stream(
    request: Request,
    session: Session = Depends(require_auth),
):
    llm = get_llm_client()

    form = await request.form()
    message = str(form.get("message", "")).strip()

    if not message:

        async def error_gen():
            yield 'data: {"error": "Empty message"}\n\n'

        return StreamingResponse(error_gen(), media_type="text/event-stream")

    llm.set_context(
        database=db,
        engine=engine,
        user_email=session.email or "user@example.com",
        user_name=session.name or "User",
    )

    chat_session = _get_or_create_session(session.user_id)

    async def generate():
        try:
            async for chunk in llm.chat_stream(chat_session, message):
                escaped = json.dumps(chunk)
                yield f"data: {escaped}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"Stream error: {e}")
            yield f"data: {json.dumps(str(e))}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/chat/clear")
async def clear_chat(
    request: Request,
    session: Session = Depends(require_auth),
):
    if session.user_id in _chat_sessions:
        del _chat_sessions[session.user_id]
    return {"status": "cleared"}


@router.get("/api/chat/history")
async def get_chat_history(
    request: Request,
    session: Session = Depends(require_auth),
):
    chat_session = _chat_sessions.get(session.user_id)
    if not chat_session:
        return {"messages": []}

    messages = []
    for msg in chat_session.messages:
        if msg.role in ("user", "assistant"):
            messages.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                }
            )

    return {"messages": messages}
