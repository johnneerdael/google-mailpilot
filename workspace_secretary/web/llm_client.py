"""
LLM client with MCP tool integration for AI chat functionality.
Supports OpenAI, Anthropic, and compatible APIs with function calling.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Callable, Optional

import httpx

from workspace_secretary.config import WebAgentConfig, WebApiFormat

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Secretary, an AI email assistant. You help users manage their email and calendar efficiently.

You have access to tools to:
- Search and read emails
- List folders and get email details
- View email threads/conversations
- Manage calendar events and check availability
- Move emails between folders
- Modify Gmail labels

When users ask about their emails or calendar, use the appropriate tools to get real data.
Be concise and helpful. Format responses clearly with bullet points or numbered lists when appropriate.

Current time: {current_time}
User's email: {user_email}
User's name: {user_name}"""


@dataclass
class ChatMessage:
    role: str
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    handler: Callable


@dataclass
class ChatSession:
    messages: list[ChatMessage] = field(default_factory=list)

    def add_user_message(self, content: str):
        self.messages.append(ChatMessage(role="user", content=content))

    def add_assistant_message(
        self, content: str, tool_calls: Optional[list[dict]] = None
    ):
        self.messages.append(
            ChatMessage(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(self, tool_call_id: str, name: str, result: str):
        self.messages.append(
            ChatMessage(
                role="tool", content=result, tool_call_id=tool_call_id, name=name
            )
        )


class LLMClient:
    def __init__(self, config: Optional[WebAgentConfig] = None):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._tools: dict[str, ToolDefinition] = {}
        self._database = None
        self._engine = None
        self._user_email: Optional[str] = None
        self._user_name: Optional[str] = None

    def set_context(self, database, engine, user_email: str, user_name: str):
        self._database = database
        self._engine = engine
        self._user_email = user_email
        self._user_name = user_name
        self._register_tools()

    @property
    def is_configured(self) -> bool:
        return self.config is not None and bool(self.config.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _register_tools(self):
        self._tools = {
            "list_folders": ToolDefinition(
                name="list_folders",
                description="List all email folders/labels in the mailbox",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self._tool_list_folders,
            ),
            "search_emails": ToolDefinition(
                name="search_emails",
                description="Search emails with filters. Returns summaries of matching emails.",
                parameters={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder to search (default: INBOX)",
                        },
                        "from_addr": {
                            "type": "string",
                            "description": "Filter by sender email/name",
                        },
                        "to_addr": {
                            "type": "string",
                            "description": "Filter by recipient",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Filter by subject keywords",
                        },
                        "body": {
                            "type": "string",
                            "description": "Filter by body keywords",
                        },
                        "unread_only": {
                            "type": "boolean",
                            "description": "Only unread emails",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 20)",
                        },
                    },
                    "required": [],
                },
                handler=self._tool_search_emails,
            ),
            "get_email_details": ToolDefinition(
                name="get_email_details",
                description="Get full details of a specific email by UID",
                parameters={
                    "type": "object",
                    "properties": {
                        "uid": {"type": "integer", "description": "Email UID"},
                        "folder": {
                            "type": "string",
                            "description": "Folder (default: INBOX)",
                        },
                    },
                    "required": ["uid"],
                },
                handler=self._tool_get_email_details,
            ),
            "get_email_thread": ToolDefinition(
                name="get_email_thread",
                description="Get all emails in a conversation thread",
                parameters={
                    "type": "object",
                    "properties": {
                        "uid": {
                            "type": "integer",
                            "description": "Any email UID in the thread",
                        },
                        "folder": {
                            "type": "string",
                            "description": "Folder (default: INBOX)",
                        },
                    },
                    "required": ["uid"],
                },
                handler=self._tool_get_email_thread,
            ),
            "get_unread_count": ToolDefinition(
                name="get_unread_count",
                description="Get count of unread emails, optionally filtered by folder",
                parameters={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder (default: all folders)",
                        },
                    },
                    "required": [],
                },
                handler=self._tool_get_unread_count,
            ),
            "list_calendar_events": ToolDefinition(
                name="list_calendar_events",
                description="List calendar events in a time range",
                parameters={
                    "type": "object",
                    "properties": {
                        "days_ahead": {
                            "type": "integer",
                            "description": "Days to look ahead (default: 7)",
                        },
                        "days_back": {
                            "type": "integer",
                            "description": "Days to look back (default: 0)",
                        },
                    },
                    "required": [],
                },
                handler=self._tool_list_calendar_events,
            ),
            "get_calendar_availability": ToolDefinition(
                name="get_calendar_availability",
                description="Check free/busy times for scheduling",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date to check (YYYY-MM-DD, default: today)",
                        },
                    },
                    "required": [],
                },
                handler=self._tool_get_calendar_availability,
            ),
            "draft_reply": ToolDefinition(
                name="draft_reply",
                description="Draft a reply to an email (does NOT send, just creates draft text)",
                parameters={
                    "type": "object",
                    "properties": {
                        "uid": {
                            "type": "integer",
                            "description": "Email UID to reply to",
                        },
                        "folder": {
                            "type": "string",
                            "description": "Folder (default: INBOX)",
                        },
                        "tone": {
                            "type": "string",
                            "description": "Tone: formal, casual, brief (default: formal)",
                        },
                        "key_points": {
                            "type": "string",
                            "description": "Key points to include in reply",
                        },
                    },
                    "required": ["uid"],
                },
                handler=self._tool_draft_reply,
            ),
            "summarize_emails": ToolDefinition(
                name="summarize_emails",
                description="Summarize recent emails or emails matching criteria",
                parameters={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder (default: INBOX)",
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Look back N hours (default: 24)",
                        },
                        "unread_only": {
                            "type": "boolean",
                            "description": "Only unread (default: true)",
                        },
                    },
                    "required": [],
                },
                handler=self._tool_summarize_emails,
            ),
        }

    async def _tool_list_folders(self, **kwargs) -> str:
        if not self._database:
            return "Database not available"
        folders = await self._database.get_folders()
        if not folders:
            return "No folders found"
        return "Folders:\n" + "\n".join(
            f"- {f['name']} ({f.get('total', 0)} emails)" for f in folders
        )

    async def _tool_search_emails(
        self,
        folder: str = "INBOX",
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 20,
        **kwargs,
    ) -> str:
        if not self._database:
            return "Database not available"

        emails = await self._database.search_emails(
            folder=folder,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body=body,
            unread_only=unread_only,
            limit=limit,
        )

        if not emails:
            return "No emails found matching criteria"

        lines = [f"Found {len(emails)} emails:"]
        for e in emails:
            date = e.get("date", "")[:10] if e.get("date") else "?"
            unread = "🔵 " if not e.get("is_read") else ""
            lines.append(
                f"- {unread}[UID {e['uid']}] {date} | From: {e.get('from_addr', '?')} | {e.get('subject', '(no subject)')}"
            )
        return "\n".join(lines)

    async def _tool_get_email_details(
        self, uid: int, folder: str = "INBOX", **kwargs
    ) -> str:
        if not self._database:
            return "Database not available"

        email = await self._database.get_email(uid, folder)
        if not email:
            return f"Email UID {uid} not found in {folder}"

        body = email.get("body_text", "") or email.get("body_html", "")
        if len(body) > 2000:
            body = body[:2000] + "...[truncated]"

        return f"""Email Details:
- UID: {uid}
- From: {email.get("from_addr", "?")}
- To: {email.get("to_addr", "?")}
- CC: {email.get("cc_addr", "") or "none"}
- Date: {email.get("date", "?")}
- Subject: {email.get("subject", "(no subject)")}
- Read: {"Yes" if email.get("is_read") else "No"}

Body:
{body}"""

    async def _tool_get_email_thread(
        self, uid: int, folder: str = "INBOX", **kwargs
    ) -> str:
        if not self._database:
            return "Database not available"

        emails = await self._database.get_thread_emails(uid, folder)
        if not emails:
            return f"No thread found for UID {uid}"

        lines = [f"Thread with {len(emails)} emails:"]
        for e in emails:
            date = e.get("date", "")[:16] if e.get("date") else "?"
            body_preview = (e.get("body_text", "") or "")[:200]
            if len(body_preview) == 200:
                body_preview += "..."
            lines.append(f"\n--- [UID {e['uid']}] {date} ---")
            lines.append(f"From: {e.get('from_addr', '?')}")
            lines.append(f"Subject: {e.get('subject', '?')}")
            lines.append(body_preview)

        return "\n".join(lines)

    async def _tool_get_unread_count(
        self, folder: Optional[str] = None, **kwargs
    ) -> str:
        if not self._database:
            return "Database not available"

        count = await self._database.get_unread_count(folder)
        if folder:
            return f"Unread in {folder}: {count}"
        return f"Total unread: {count}"

    async def _tool_list_calendar_events(
        self, days_ahead: int = 7, days_back: int = 0, **kwargs
    ) -> str:
        if not self._engine:
            return "Calendar not available"

        now = datetime.now()
        time_min = (now - timedelta(days=days_back)).isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        try:
            events = await self._engine.list_calendar_events(time_min, time_max)
            if not events:
                return "No events found in the specified time range"

            lines = [f"Calendar events ({len(events)}):"]
            for ev in events:
                start = ev.get("start", {}).get(
                    "dateTime", ev.get("start", {}).get("date", "?")
                )
                lines.append(f"- {start[:16]} | {ev.get('summary', '(no title)')}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching calendar: {e}"

    async def _tool_get_calendar_availability(
        self, date: Optional[str] = None, **kwargs
    ) -> str:
        if not self._engine:
            return "Calendar not available"

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        try:
            availability = await self._engine.get_calendar_availability(date)
            return f"Availability for {date}:\n{availability}"
        except Exception as e:
            return f"Error checking availability: {e}"

    async def _tool_draft_reply(
        self,
        uid: int,
        folder: str = "INBOX",
        tone: str = "formal",
        key_points: Optional[str] = None,
        **kwargs,
    ) -> str:
        if not self._database:
            return "Database not available"

        email = await self._database.get_email(uid, folder)
        if not email:
            return f"Email UID {uid} not found"

        sender = email.get("from_addr", "")
        subject = email.get("subject", "")
        body_preview = (email.get("body_text", "") or "")[:500]

        draft = f"""Draft reply to: {sender}
Subject: Re: {subject}

---
[Draft - {tone} tone]

"""
        if key_points:
            draft += f"Key points to address: {key_points}\n\n"

        draft += f"Original message preview:\n{body_preview}\n\n"
        draft += "---\nNote: This is a draft outline. Please review and customize before sending."

        return draft

    async def _tool_summarize_emails(
        self,
        folder: str = "INBOX",
        hours: int = 24,
        unread_only: bool = True,
        **kwargs,
    ) -> str:
        if not self._database:
            return "Database not available"

        emails = await self._database.search_emails(
            folder=folder,
            unread_only=unread_only,
            limit=50,
        )

        if not emails:
            return f"No {'unread ' if unread_only else ''}emails in {folder}"

        cutoff = datetime.now() - timedelta(hours=hours)
        recent = []
        for e in emails:
            try:
                email_date = datetime.fromisoformat(
                    e.get("date", "").replace("Z", "+00:00")
                )
                if email_date.replace(tzinfo=None) > cutoff:
                    recent.append(e)
            except (ValueError, TypeError):
                recent.append(e)

        if not recent:
            return f"No emails in the last {hours} hours"

        by_sender: dict[str, list] = {}
        for e in recent:
            sender = e.get("from_addr", "Unknown")
            by_sender.setdefault(sender, []).append(e)

        lines = [f"Summary of {len(recent)} emails in last {hours}h:"]
        for sender, sender_emails in sorted(
            by_sender.items(), key=lambda x: -len(x[1])
        ):
            lines.append(f"\n**{sender}** ({len(sender_emails)} emails):")
            for e in sender_emails[:3]:
                lines.append(f"  - {e.get('subject', '(no subject)')}")
            if len(sender_emails) > 3:
                lines.append(f"  - ...and {len(sender_emails) - 3} more")

        return "\n".join(lines)

    def _get_tools_for_api(self) -> list[dict]:
        if self.config and self.config.api_format == WebApiFormat.ANTHROPIC_CHAT:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in self._tools.values()
            ]
        else:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in self._tools.values()
            ]

    def _build_headers(self) -> dict:
        if not self.config:
            return {}

        headers = {"Content-Type": "application/json"}

        if self.config.api_format == WebApiFormat.ANTHROPIC_CHAT:
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        return headers

    def _build_messages_for_api(
        self, session: ChatSession
    ) -> tuple[Optional[str], list[dict]]:
        system_content = SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            user_email=self._user_email or "unknown",
            user_name=self._user_name or "User",
        )

        if self.config and self.config.api_format == WebApiFormat.ANTHROPIC_CHAT:
            messages: list[dict[str, Any]] = []
            for msg in session.messages:
                if msg.role == "tool":
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": msg.tool_call_id,
                                    "content": msg.content,
                                }
                            ],
                        }
                    )
                elif msg.role == "assistant" and msg.tool_calls:
                    content = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "input": json.loads(tc["function"]["arguments"]),
                            }
                        )
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": msg.role, "content": msg.content})
            return system_content, messages
        else:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_content}
            ]
            for msg in session.messages:
                if msg.role == "tool":
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    )
                elif msg.role == "assistant" and msg.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content or "",
                            "tool_calls": msg.tool_calls,
                        }
                    )
                else:
                    messages.append({"role": msg.role, "content": msg.content})
            return None, messages

    def _build_request_body(self, session: ChatSession, stream: bool = False) -> dict:
        if not self.config:
            return {}

        system_content, messages = self._build_messages_for_api(session)
        tools = self._get_tools_for_api()

        if self.config.api_format == WebApiFormat.ANTHROPIC_CHAT:
            body = {
                "model": self.config.model,
                "max_tokens": 4096,
                "messages": messages,
                "tools": tools,
                "stream": stream,
            }
            if system_content:
                body["system"] = system_content
            return body
        else:
            return {
                "model": self.config.model,
                "messages": messages,
                "tools": tools,
                "stream": stream,
            }

    def _get_endpoint(self) -> str:
        if not self.config:
            return ""

        base = self.config.base_url.rstrip("/")

        if self.config.api_format == WebApiFormat.ANTHROPIC_CHAT:
            return f"{base}/messages"
        else:
            return f"{base}/chat/completions"

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Unknown tool: {name}"

        try:
            result = await tool.handler(**arguments)
            return result
        except Exception as e:
            logger.exception(f"Tool {name} failed: {e}")
            return f"Tool error: {e}"

    async def chat(self, session: ChatSession, user_message: str) -> str:
        if not self.is_configured:
            return (
                "AI assistant not configured. Please set up the agent in config.yaml."
            )

        session.add_user_message(user_message)

        client = await self._get_client()
        headers = self._build_headers()
        endpoint = self._get_endpoint()

        max_tool_rounds = 5
        for _ in range(max_tool_rounds):
            body = self._build_request_body(session, stream=False)

            try:
                response = await client.post(endpoint, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()

                if (
                    self.config
                    and self.config.api_format == WebApiFormat.ANTHROPIC_CHAT
                ):
                    content_blocks = data.get("content", [])
                    text_content = ""
                    tool_calls = []

                    for block in content_blocks:
                        if block.get("type") == "text":
                            text_content += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block["id"],
                                    "type": "function",
                                    "function": {
                                        "name": block["name"],
                                        "arguments": json.dumps(block.get("input", {})),
                                    },
                                }
                            )

                    if tool_calls:
                        session.add_assistant_message(text_content, tool_calls)
                        for tc in tool_calls:
                            result = await self._execute_tool(
                                tc["function"]["name"],
                                json.loads(tc["function"]["arguments"]),
                            )
                            session.add_tool_result(
                                tc["id"], tc["function"]["name"], result
                            )
                        continue
                    else:
                        session.add_assistant_message(text_content)
                        return text_content
                else:
                    choice = data["choices"][0]
                    message = choice["message"]

                    if message.get("tool_calls"):
                        tool_calls = message["tool_calls"]
                        session.add_assistant_message(
                            message.get("content", ""), tool_calls
                        )

                        for tc in tool_calls:
                            result = await self._execute_tool(
                                tc["function"]["name"],
                                json.loads(tc["function"]["arguments"]),
                            )
                            session.add_tool_result(
                                tc["id"], tc["function"]["name"], result
                            )
                        continue
                    else:
                        content = message.get("content", "")
                        session.add_assistant_message(content)
                        return content

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"LLM API error: {e.response.status_code} - {e.response.text}"
                )
                return f"Error: API returned {e.response.status_code}"
            except Exception as e:
                logger.exception(f"LLM error: {e}")
                error_msg = str(e)
                if (
                    "No address associated with hostname" in error_msg
                    or "getaddrinfo failed" in error_msg
                ):
                    return "Error: Unable to connect to LLM service. Please check that the AI assistant is properly configured in config.yaml under 'web.agent' section with a valid base_url and api_key."
                return f"Error: {error_msg}"

        return "Reached maximum tool execution rounds. Please try a simpler request."

    async def chat_stream(
        self, session: ChatSession, user_message: str
    ) -> AsyncIterator[str]:
        if not self.is_configured:
            yield "AI assistant not configured. Please set up the agent in config.yaml."
            return

        session.add_user_message(user_message)

        client = await self._get_client()
        headers = self._build_headers()
        endpoint = self._get_endpoint()

        max_tool_rounds = 5
        for round_num in range(max_tool_rounds):
            body = self._build_request_body(session, stream=True)

            try:
                collected_content = ""
                collected_tool_calls: dict[int, dict] = {}

                async with client.stream(
                    "POST", endpoint, headers=headers, json=body
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)

                            if (
                                self.config
                                and self.config.api_format
                                == WebApiFormat.ANTHROPIC_CHAT
                            ):
                                pass
                            else:
                                choices = data.get("choices", [])
                                if not choices:
                                    continue

                                delta = choices[0].get("delta", {})

                                if content := delta.get("content"):
                                    collected_content += content
                                    yield content

                                if tool_calls := delta.get("tool_calls"):
                                    for tc in tool_calls:
                                        idx = tc.get("index", 0)
                                        if idx not in collected_tool_calls:
                                            collected_tool_calls[idx] = {
                                                "id": tc.get("id", ""),
                                                "type": "function",
                                                "function": {
                                                    "name": "",
                                                    "arguments": "",
                                                },
                                            }
                                        if tc.get("id"):
                                            collected_tool_calls[idx]["id"] = tc["id"]
                                        if func := tc.get("function"):
                                            if func.get("name"):
                                                collected_tool_calls[idx]["function"][
                                                    "name"
                                                ] = func["name"]
                                            if func.get("arguments"):
                                                collected_tool_calls[idx]["function"][
                                                    "arguments"
                                                ] += func["arguments"]

                        except json.JSONDecodeError:
                            continue

                if collected_tool_calls:
                    tool_calls_list = list(collected_tool_calls.values())
                    session.add_assistant_message(collected_content, tool_calls_list)

                    yield "\n\n🔧 _Using tools..._\n"

                    for tc in tool_calls_list:
                        tool_name = tc["function"]["name"]
                        yield f"- {tool_name}\n"
                        result = await self._execute_tool(
                            tool_name,
                            json.loads(tc["function"]["arguments"]),
                        )
                        session.add_tool_result(tc["id"], tool_name, result)

                    yield "\n"
                    continue
                else:
                    session.add_assistant_message(collected_content)
                    return

            except httpx.HTTPStatusError as e:
                logger.error(f"LLM API error: {e.response.status_code}")
                yield f"\n\nError: API returned {e.response.status_code}"
                return
            except Exception as e:
                logger.exception(f"LLM stream error: {e}")
                error_msg = str(e)
                if (
                    "No address associated with hostname" in error_msg
                    or "getaddrinfo failed" in error_msg
                ):
                    yield "\n\nError: Unable to connect to LLM service. Please check that the AI assistant is properly configured in config.yaml under 'web.agent' section with a valid base_url and api_key."
                else:
                    yield f"\n\nError: {error_msg}"
                return

        yield "\n\nReached maximum tool execution rounds."


_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def init_llm_client(config: Optional[WebAgentConfig]):
    global _llm_client
    _llm_client = LLMClient(config)
    logger.info(f"LLM client initialized: configured={_llm_client.is_configured}")
