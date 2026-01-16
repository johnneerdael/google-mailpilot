"""LangGraph StateGraph for the chat assistant.

This module defines the main conversation graph with:
- LLM reasoning node with bound tools
- Separate ToolNodes for read-only and mutation tools
- Human-in-the-loop via interrupt_before for mutations
- Batch operation support with continuation state
- PostgreSQL checkpointer for conversation persistence
"""

import json
import logging
from typing import Any, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from workspace_secretary.assistant.state import AssistantState
from workspace_secretary.assistant.context import (
    AssistantContext,
    set_context,
    get_context,
)
from workspace_secretary.assistant.tool_registry import (
    get_all_tools,
    get_readonly_tools,
    get_mutation_tools,
    is_mutation_tool,
    is_batch_tool,
)
from workspace_secretary.assistant.checkpointer import create_checkpointer
from workspace_secretary.config import ServerConfig, WebApiFormat

logger = logging.getLogger(__name__)

# Global compiled graph instance
_graph = None

# System prompt for the assistant
SYSTEM_PROMPT = """You are an intelligent email secretary for {user_name} ({user_email}).

## Capabilities
- Search, read, and analyze emails
- Triage inbox with smart classification (pattern matching + LLM)
- Create draft replies (safe, no approval needed)
- Apply labels and organize emails (requires approval)
- Manage calendar events

## CRITICAL: Tool Chaining Workflows

### /triage - Smart Inbox Triage
1. Call `triage_inbox()` to classify emails into categories
2. Results include:
   - high_confidence (>90%): Auto-apply labels without asking
   - needs_review (<90%): Show samples, ask for approval
3. Categories: action-required, fyi, newsletter, notification, cleanup
4. After triage, call `apply_triage_labels(classifications_json=...)` with the results

### /clean - Inbox Cleanup  
1. Call `quick_clean_inbox()` to find cleanup candidates
2. Results include `candidates` array with UIDs
3. On user approval ("yes", "archive them"), extract UIDs and call:
   `execute_clean_batch(uids=[list of candidate UIDs])`

### /priority - Priority Emails
1. Call `triage_inbox()` and filter for `action-required` category
2. Show only emails needing user response
3. Offer to draft replies or show full content

## Label Structure
- Secretary/Action-Required: Direct questions needing response
- Secretary/FYI: CC'd, informational, no action needed
- Secretary/Newsletter: Marketing, digests (auto: mark read + archive)
- Secretary/Notification: Zoom, GitHub, etc (auto: mark read)
- Secretary/Auto-Cleaned: Archived low-priority
- Secretary/Waiting: Sent by you, awaiting reply
- Secretary/Processed: Action taken

## Rules (from AGENTS.md)
- NEVER send emails without explicit approval
- High confidence (>90%): Auto-apply labels, report summary only
- Lower confidence: Show samples, ask before applying actions
- create_draft_reply is SAFE (creates Gmail draft, doesn't send)

## User Context
- Timezone: {timezone}
- Working Hours: {working_hours}

Be concise. When user says "yes" or "do it", execute the pending action immediately."""


def create_llm(config: ServerConfig) -> BaseChatModel:
    """Create the appropriate LLM based on configuration.

    Args:
        config: Server configuration with web agent settings

    Returns:
        Configured LangChain chat model

    Raises:
        ValueError: If web or agent config is not configured
    """
    if config.web is None:
        raise ValueError("Web configuration required for LangGraph assistant")

    agent_config = config.web.agent
    api_format = agent_config.api_format

    if api_format == WebApiFormat.GEMINI:
        return ChatGoogleGenerativeAI(
            model=agent_config.model,
            google_api_key=agent_config.api_key,
            temperature=0.7,
            max_output_tokens=agent_config.token_limit,
        )
    elif api_format == WebApiFormat.ANTHROPIC_CHAT:
        return ChatAnthropic(
            model=agent_config.model,
            anthropic_api_key=agent_config.api_key,
            temperature=0.7,
            max_tokens=agent_config.token_limit,
        )
    elif api_format == WebApiFormat.OPENAI_CHAT:
        return ChatOpenAI(
            model=agent_config.model,
            api_key=agent_config.api_key,
            base_url=agent_config.base_url if agent_config.base_url else None,
            temperature=0.7,
            max_tokens=agent_config.token_limit,
        )
    else:
        raise ValueError(f"Unsupported API format: {api_format}")


def format_system_prompt(state: AssistantState) -> str:
    """Format the system prompt with user context.

    Args:
        state: Current assistant state

    Returns:
        Formatted system prompt string
    """
    return SYSTEM_PROMPT.format(
        user_email=state["user_email"],
        user_name=state["user_name"],
        timezone=state["timezone"],
        working_hours=state["working_hours"],
    )


def llm_node(state: AssistantState, config: RunnableConfig) -> dict[str, Any]:
    """LLM reasoning node that generates responses and tool calls.

    Args:
        state: Current conversation state
        config: Runtime configuration (contains 'configurable' with llm)

    Returns:
        State update with new messages
    """
    llm: BaseChatModel = config["configurable"]["llm"]

    # Build messages with system prompt
    system_msg = SystemMessage(content=format_system_prompt(state))
    messages = [system_msg] + list(state["messages"])

    # Invoke LLM
    response = llm.invoke(messages)

    return {"messages": [response]}


def route_after_llm(
    state: AssistantState,
) -> str:
    """Route based on the last AI message's tool calls."""
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage):
        return END

    if not last_message.tool_calls:
        return END

    for tool_call in last_message.tool_calls:
        if is_mutation_tool(tool_call["name"]):
            return "mutation_tools"
        if is_batch_tool(tool_call["name"]):
            return "batch_runner"

    return "readonly_tools"


def batch_runner_node(state: AssistantState, config: RunnableConfig) -> dict[str, Any]:
    """Execute batch tools with continuation support.

    Runs the ENTIRE batch operation to completion, aggregating all results.
    This avoids graph recursion by looping internally until done.
    Supports up to 2000+ emails by continuing until has_more=false.
    Emits progress events for UI updates.
    """
    from langgraph.types import Command
    from langchain_core.callbacks import dispatch_custom_event

    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"batch_status": "complete"}

    batch_tool_call = None
    for tc in last_message.tool_calls:
        if is_batch_tool(tc["name"]):
            batch_tool_call = tc
            break

    if not batch_tool_call:
        return {"batch_status": "complete"}

    tool_name = batch_tool_call["name"]
    base_args = batch_tool_call["args"].copy()

    from workspace_secretary.assistant.tools_read import (
        quick_clean_inbox,
        triage_priority_emails,
        triage_remaining_emails,
    )

    tool_map = {
        "quick_clean_inbox": quick_clean_inbox,
        "triage_priority_emails": triage_priority_emails,
        "triage_remaining_emails": triage_remaining_emails,
    }
    tool_fn = tool_map.get(tool_name)

    if not tool_fn:
        error_msg = ToolMessage(
            content=f"Unknown batch tool: {tool_name}",
            tool_call_id=batch_tool_call["id"],
        )
        return {"messages": [error_msg], "batch_status": "complete"}

    # Run the entire batch operation to completion
    all_items = []
    total_processed = 0
    continuation_state = None
    iteration = 0
    max_iterations = 500  # Safety limit for 2000+ emails
    total_estimate = 0

    # Emit start event
    dispatch_custom_event(
        "batch_progress",
        {
            "tool": tool_name,
            "status": "starting",
            "processed": 0,
            "total_estimate": 0,
            "items_found": 0,
            "iteration": 0,
        },
        config=config,
    )

    while iteration < max_iterations:
        iteration += 1
        tool_args = base_args.copy()
        if continuation_state:
            tool_args["continuation_state"] = continuation_state

        try:
            result_str = tool_fn.invoke(tool_args)
            result = (
                json.loads(result_str)
                if result_str.startswith("{")
                else {"raw": result_str}
            )
        except Exception as e:
            logger.error(f"Batch tool error on iteration {iteration}: {e}")
            dispatch_custom_event(
                "batch_progress",
                {
                    "tool": tool_name,
                    "status": "error",
                    "error": str(e),
                    "processed": total_processed,
                    "items_found": len(all_items),
                    "iteration": iteration,
                },
                config=config,
            )
            error_msg = ToolMessage(
                content=f"Batch tool error: {e}",
                tool_call_id=batch_tool_call["id"],
            )
            return {"messages": [error_msg], "batch_status": "complete"}

        # Aggregate results - check all possible keys from different tools
        new_items = result.get(
            "candidates", result.get("priority_emails", result.get("emails", []))
        )
        all_items.extend(new_items)
        total_processed += result.get("processed_count", len(new_items))
        total_estimate = (
            result.get("total_available", total_estimate) or total_processed
        )

        has_more = result.get("has_more", False)
        continuation_state = result.get("continuation_state")

        # Emit progress event
        dispatch_custom_event(
            "batch_progress",
            {
                "tool": tool_name,
                "status": "running" if has_more else "complete",
                "processed": total_processed,
                "total_estimate": total_estimate,
                "items_found": len(all_items),
                "has_more": has_more,
                "iteration": iteration,
            },
            config=config,
        )

        logger.info(
            f"Batch iteration {iteration}: +{len(new_items)} items, total={len(all_items)}, has_more={has_more}"
        )

        if not has_more or not continuation_state:
            break

    # Return complete results to LLM
    tool_result = ToolMessage(
        content=json.dumps(
            {
                "status": "complete",
                "total_items": len(all_items),
                "processed_count": total_processed,
                "iterations": iteration,
                "items": all_items,
            }
        ),
        tool_call_id=batch_tool_call["id"],
    )

    return {
        "messages": [tool_result],
        "batch_status": "complete",
        "batch_tool": None,
        "batch_args": None,
        "batch_continuation_state": None,
        "batch_items": [],
        "batch_processed_count": 0,
    }


def route_after_batch(state: AssistantState) -> str:
    """Route after batch runner - always return to LLM with complete results."""
    return "llm"


def route_after_tools(state: AssistantState) -> str:
    """Route after tool execution - always return to LLM for reasoning."""
    return "llm"


def create_assistant_graph(
    context: AssistantContext,
) -> StateGraph:
    """Create the assistant StateGraph."""
    global _graph

    set_context(context)

    llm = create_llm(context.config)
    all_tools = get_all_tools()
    llm_with_tools = llm.bind_tools(all_tools)

    readonly_tools = get_readonly_tools()
    mutation_tools = get_mutation_tools()

    readonly_node = ToolNode(readonly_tools)
    mutation_node = ToolNode(mutation_tools)

    builder = StateGraph(AssistantState)

    builder.add_node("llm", llm_node)
    builder.add_node("readonly_tools", readonly_node)
    builder.add_node("mutation_tools", mutation_node)
    builder.add_node("batch_runner", batch_runner_node)

    builder.add_edge(START, "llm")

    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {
            "readonly_tools": "readonly_tools",
            "mutation_tools": "mutation_tools",
            "batch_runner": "batch_runner",
            END: END,
        },
    )

    builder.add_edge("readonly_tools", "llm")
    builder.add_edge("mutation_tools", "llm")

    builder.add_conditional_edges(
        "batch_runner",
        route_after_batch,
        {
            "llm": "llm",
        },
    )

    checkpointer = None
    if context.config.database.backend == "postgres":
        checkpointer = create_checkpointer(context.config.database.postgres)

    _graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["mutation_tools"],
    )

    _graph.llm = llm_with_tools

    logger.info("Assistant graph created with batch support")
    return _graph


def get_graph() -> StateGraph:
    """Get the compiled graph instance.

    Returns:
        The compiled StateGraph

    Raises:
        RuntimeError: If graph not initialized
    """
    if _graph is None:
        raise RuntimeError(
            "Assistant graph not initialized. Call create_assistant_graph() first."
        )
    return _graph


async def invoke_graph(
    state: AssistantState,
    thread_id: str,
    resume: bool = False,
) -> AssistantState:
    """Invoke the graph for a conversation turn.

    Args:
        state: Current conversation state
        thread_id: Unique thread identifier for checkpointing
        resume: If True, resume from interrupt (approve mutation)

    Returns:
        Updated state after graph execution
    """
    graph = get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "llm": graph.llm,
        },
        "recursion_limit": 2000,  # Allow many iterations for batch operations (2000+ emails)
    }

    if resume:
        # Resume from interrupt - continue execution
        result = await graph.ainvoke(None, config)
    else:
        # Normal invocation with state
        result = await graph.ainvoke(state, config)

    return result


async def stream_graph(
    state: Optional[AssistantState],
    thread_id: str,
    resume: bool = False,
):
    """Stream graph execution events.

    Args:
        state: Current conversation state
        thread_id: Unique thread identifier
        resume: If True, resume from interrupt

    Yields:
        Graph events as they occur
    """
    graph = get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "llm": graph.llm,
        },
        "recursion_limit": 500,  # Allow many iterations for batch operations (1000+ emails)
    }

    input_state = None if resume else state

    async for event in graph.astream_events(input_state, config, version="v2"):
        yield event


def get_pending_mutation(thread_id: str) -> Optional[dict[str, Any]]:
    """Get the pending mutation tool call for a thread.

    Used to retrieve the mutation awaiting user approval.

    Args:
        thread_id: Thread identifier

    Returns:
        Pending tool call dict or None
    """
    graph = get_graph()

    config = {"configurable": {"thread_id": thread_id}}

    # Get current state from checkpointer
    try:
        state = graph.get_state(config)
    except ValueError:
        # No checkpointer set
        return None

    if state and state.values:
        messages = state.values.get("messages", [])
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                for tool_call in last_message.tool_calls:
                    if is_mutation_tool(tool_call["name"]):
                        return tool_call

    return None


def reject_mutation(
    thread_id: str, reason: str = "User declined"
) -> Optional[AssistantState]:
    """Reject a pending mutation and add rejection message.

    Args:
        thread_id: Thread identifier
        reason: Rejection reason to add to conversation

    Returns:
        Updated state with rejection message, or None if no checkpointer
    """
    graph = get_graph()

    config = {"configurable": {"thread_id": thread_id}}

    # Get current state
    try:
        state = graph.get_state(config)
    except ValueError:
        # No checkpointer set
        return None

    if state and state.values:
        messages = list(state.values.get("messages", []))
        last_message = messages[-1] if messages else None

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            # Add tool result message indicating rejection
            for tool_call in last_message.tool_calls:
                if is_mutation_tool(tool_call["name"]):
                    rejection_msg = ToolMessage(
                        content=f"Action rejected by user: {reason}",
                        tool_call_id=tool_call["id"],
                    )
                    messages.append(rejection_msg)

            # Update state with rejection
            new_state = {**state.values, "messages": messages}

            # Use update_state to apply the rejection
            graph.update_state(config, new_state)

    return graph.get_state(config).values
