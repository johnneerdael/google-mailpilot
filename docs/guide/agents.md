# Agentic Framework: Building AI Secretaries with Google MailPilot MCP

The Google MailPilot MCP is designed to be consumed by Large Language Models (LLMs) acting as autonomous or semi-autonomous agents. This document defines the patterns for building safe, effective AI assistants with proper safeguards.

## 🎯 Core Principles

### 1. Human-in-the-Loop (HITL) for Mutations
**Critical Rule**: All tools that **modify state** (send emails, delete messages, move to trash) MUST require explicit user confirmation.

**The Draft-Review-Send Pattern:**
```
1. AI: Analyze situation and prepare action
2. AI: Use safe tool (create_draft_reply) to prepare content
3. AI: Present draft to user: "I've prepared this reply. Would you like me to send it?"
4. USER: Review and approve: "Yes, send it" / "No, revise the tone"
5. AI: Execute only after confirmation (send_email)
```

**Example Safe Interaction:**
```
User: "Reply to John's email saying I'll be 10 minutes late"
AI: ❌ [Does NOT immediately call send_email()]
AI: ✅ "I've drafted this reply to John:
     
     Subject: Re: Team Meeting Today
     
     Hi John,
     
     I'll be about 10 minutes late to our meeting. Please start without me if needed.
     
     Thanks,
     [Your name]
     
     Would you like me to send this?"

User: "Yes"
AI: ✅ [Calls send_email()] "Email sent successfully!"
```

### 2. Signals Over Decisions
The new intelligence features provide **signals** for the LLM to interpret, not hardcoded decisions:

- ✅ Good: "This email has `is_from_vip=true` and `mentions_deadline=true`"
- ❌ Bad: "This email is high priority" (tool should not decide)

**Why?** Context matters. An "urgent" email on Friday at 5 PM might be less important than a calm question from your CEO.

### 3. Timezone Awareness
All scheduling operations must respect the user's configured timezone and working hours:
- ✅ Use `get_daily_briefing(date="2026-01-09")` - auto-uses user's timezone
- ✅ Use `suggest_reschedule()` - only suggests slots within working_hours
- ❌ Don't hardcode "9 AM EST" - user might be in Tokyo

## 🤖 Agent Personas

### The Morning Briefing Agent
**Focus**: Daily intelligence digest with prioritized action items.

**Primary Tools**: 
- `get_daily_briefing(date=today)`

**Workflow**:
```python
1. briefing = call get_daily_briefing()
2. Parse briefing.email_candidates
3. Prioritize by signals:
   - is_from_vip=true → Top priority
   - mentions_deadline=true + has_question=true → Urgent action needed
   - is_important=true (Gmail's own signal)
4. Present summary:
   "Good morning! You have 3 VIP emails, 5 questions needing responses,
    and 2 items with deadlines today. Your first meeting is at 10 AM."
```

**System Prompt Example**:
```
You are a Morning Briefing Secretary. Each day, you:
1. Call get_daily_briefing() for today
2. Analyze email_candidates using the 5 signals
3. Identify: VIP senders, urgent deadlines, unanswered questions
4. Present a concise summary (< 200 words) with recommended actions
5. NEVER send emails without user confirmation
```

### The Triage Agent
**Focus**: Continuous inbox monitoring and intelligent filtering.

**Primary Tools**: 
- `get_unread_messages(limit=20)`
- `search_emails(query="is:unread")`
- `get_email_details(message_id)`

**Workflow**:
```python
1. Fetch unread messages
2. For each email, check:
   - Sender (is it a VIP?)
   - Subject (does it mention meetings, deadlines, or contain "?")
   - Gmail labels (IMPORTANT, CATEGORY_PERSONAL vs CATEGORY_PROMOTIONS)
3. Categorize:
   - "Needs Response" (has_question=true, not a newsletter)
   - "FYI Only" (no question, not from VIP)
   - "Newsletter/Promo" (category labels)
4. Present triage report to user
```

**System Prompt Example**:
```
You are a Triage Secretary. You run every 30 minutes to:
1. Scan for new unread emails
2. Categorize by urgency (VIP, deadline, question, FYI)
3. Alert user only for high-priority items
4. Suggest: "Reply now", "Review later", or "Archive"
5. NEVER delete or move emails without asking first
```

### The Scheduling Agent
**Focus**: Calendar management, conflict resolution, timezone-aware scheduling.

**Primary Tools**: 
- `check_calendar(time_min, time_max)`
- `suggest_reschedule(thread_id, suggested_date)`
- `process_meeting_invite(thread_id)`

**Workflow**:
```python
1. User: "I need to reschedule my 2 PM with Sarah to next week"
2. Extract context: who=Sarah, current_time=2 PM, target=next week
3. Call suggest_reschedule(thread_id, suggested_date="2026-01-15")
   - Automatically respects working_hours
   - Only suggests times on workdays
   - Timezone-aware (no manual conversion needed)
4. Present options: "Here are 3 alternatives during your working hours..."
5. User confirms
6. Create draft reply with selected time
```

**System Prompt Example**:
```
You are a Scheduling Secretary. For meeting requests:
1. Always check calendar availability before committing
2. Use suggest_reschedule() to find slots within working hours
3. Prefer 30-min buffer between meetings
4. Draft polite meeting responses
5. NEVER accept/decline meetings without user approval
```

### The Intelligence Clerk
**Focus**: Document extraction, thread analysis, knowledge retrieval.

**Primary Tools**: 
- `get_attachment_content(message_id, attachment_id)`
- `summarize_thread(thread_id)`
- `get_thread(thread_id)`
- `search_emails(query=advanced_criteria)`

**Workflow**:
```python
1. User: "What did the contract say about payment terms?"
2. Search for contract: search_emails(keyword="contract", from="legal@")
3. Get email details to find PDF attachment
4. Extract text: get_attachment_content()
5. Parse for "payment terms" section
6. Summarize findings
```

**System Prompt Example**:
```
You are an Intelligence Clerk. When asked about past communications:
1. Use search_emails() to find relevant threads
2. Use summarize_thread() for quick context
3. Use get_attachment_content() to read PDFs/DOCX
4. Provide citations (email date, sender, subject)
5. NEVER fabricate information not in the emails
```

## 🛡️ Safety Patterns

### Pattern 1: Mutation Confirmation
```python
# ❌ NEVER do this:
def dangerous_agent(user_request):
    if "delete" in user_request:
        process_email(uid=123, action="delete")  # NO!

# ✅ ALWAYS do this:
def safe_agent(user_request):
    if "delete" in user_request:
        print(f"This will permanently delete email from {sender}.")
        print("Confirm: yes/no")
        if user_confirms():
            process_email(uid=123, action="delete")
        else:
            print("Cancelled.")
```

### Pattern 2: Show Before Send
```python
# ✅ Two-step email sending:
def compose_and_send(recipient, subject, body):
    # Step 1: Show draft
    draft = create_draft_reply(to=recipient, subject=subject, body=body)
    print(f"Draft created:")
    print(f"To: {recipient}")
    print(f"Subject: {subject}")
    print(f"Body: {body}")
    print("\nSend this email? (yes/no)")
    
    # Step 2: Only send if confirmed
    if user_confirms():
        send_email(to=recipient, subject=subject, body=body)
        print("✅ Email sent!")
    else:
        print("❌ Cancelled. Draft saved for editing.")
```

### Pattern 3: VIP Priority Routing
```python
# Use signals to route high-priority items:
def check_new_emails():
    briefing = get_daily_briefing()
    
    vip_emails = [e for e in briefing["email_candidates"] 
                  if e["signals"]["is_from_vip"]]
    
    if vip_emails:
        # Immediate alert for VIP emails
        alert_user(f"🚨 {len(vip_emails)} emails from VIPs need attention!")
        for email in vip_emails:
            show_preview(email)
    
    # Process other emails on normal schedule
    other_emails = [e for e in briefing["email_candidates"]
                    if not e["signals"]["is_from_vip"]]
    summarize_batch(other_emails)
```

## 🔧 Tool Orchestration Examples

### Example 1: "Give me my daily briefing"
```
1. Call: get_daily_briefing(date="2026-01-08")
2. Receive: {calendar_events: [...], email_candidates: [...]}
3. Analyze email_candidates:
   - Count by signal (3 VIPs, 7 questions, 2 deadlines)
   - Identify trends (lots of meeting requests today)
4. Present:
   "Morning briefing for Wednesday, Jan 8:
    - 3 meetings today (10 AM, 2 PM, 4 PM)
    - 3 emails from VIPs (boss, CEO, lead client)
    - 7 emails with questions needing replies
    - 2 items mention today's deadline"
```

### Example 2: "Reschedule my 2 PM meeting to Friday"
```
1. Call: check_calendar(time_min="2026-01-08T14:00", time_max="2026-01-08T15:00")
2. Identify meeting: "Project Sync with Sarah, 2-3 PM"
3. Extract thread_id from meeting description or search emails
4. Call: suggest_reschedule(thread_id=thread_id, suggested_date="2026-01-10")
5. Receive: 3 slots within working hours (10 AM, 2 PM, 4 PM)
6. Draft: "Hi Sarah, I need to move our Wed meeting. Would Fri at 10 AM, 2 PM, or 4 PM work?"
7. Ask user to review
8. User: "10 AM looks good"
9. Create draft with finalized time
10. User: "Send it"
11. Call: send_email()
```

### Example 3: "What's my most important email right now?"
```
1. Call: get_daily_briefing()
2. Score each email_candidate:
   score = (is_from_vip * 3) + (mentions_deadline * 2) + (has_question * 1) + (is_important * 1)
3. Top email: score=6 (VIP + deadline + question)
4. Call: get_email_details(message_id=top_email_id)
5. Present:
   "Your CEO sent an email 2 hours ago asking about Q4 numbers (due EOD).
    This requires a response today. Would you like me to draft a reply?"
```

## 🚀 Multi-Agent Coordination

If using frameworks like LangGraph, CrewAI, or AutoGen:

### Router Agent Pattern
```python
def route_request(user_input):
    if mentions_scheduling(user_input):
        return SchedulingAgent()
    elif mentions_search_or_past(user_input):
        return IntelligenceClerk()
    elif mentions_inbox_or_triage(user_input):
        return TriageAgent()
    else:
        return ChiefOfStaffAgent()  # Orchestrates others
```

### Parallel Execution Pattern
```python
# Execute briefing tasks in parallel:
async def morning_routine():
    briefing, unread_count, vip_status = await asyncio.gather(
        get_daily_briefing(),
        count_unread(),
        check_vip_emails()
    )
    return combine_insights(briefing, unread_count, vip_status)
```

## ⏱️ Time-Boxed Batch Processing Pattern

**CRITICAL**: Batch tools (`quick_clean_inbox`, `triage_priority_emails`, `triage_remaining_emails`) are **time-boxed** to ~5 seconds per call to avoid MCP timeouts. Agents MUST implement autonomous continuation loops.

### Why Time-Boxing?

MCP has strict timeout limits. Processing 500 emails in one call would timeout. Instead:
- Each call processes emails for ~5 seconds
- Returns partial results with `continuation_state`
- Agent continues automatically until complete

### The Autonomous Continuation Pattern

```python
async def bulk_cleanup_agent():
    """
    Subagent that autonomously gathers ALL cleanup candidates
    before returning to the orchestrator for user approval.
    """
    all_candidates = []
    continuation_state = None
    
    # Autonomous loop - NO user interaction during gathering
    while True:
        result = await call_tool(
            "quick_clean_inbox",
            continuation_state=continuation_state
        )
        
        # Aggregate candidates from this batch
        all_candidates.extend(result["candidates"])
        
        # Check if done
        if result["status"] == "complete" or not result["has_more"]:
            break
        
        # Continue with state from response
        continuation_state = result["continuation_state"]
    
    # Return COMPLETE aggregated results (not partial)
    return {
        "total_candidates": len(all_candidates),
        "candidates": all_candidates,
        "status": "complete"
    }
```

### Orchestrator Pattern

```python
async def secretary_orchestrator(user_request):
    """
    Primary agent that delegates to subagents and handles user approval.
    """
    if user_request == "/clean-inbox":
        # Step 1: Delegate to subagent (runs autonomous loop)
        cleanup_result = await bulk_cleanup_agent()
        
        # Step 2: Present COMPLETE results to user (single prompt)
        approval = await present_to_user(
            f"Found {cleanup_result['total_candidates']} emails to clean. "
            f"Approve? (yes/no)"
        )
        
        # Step 3: Execute only if approved
        if approval == "yes":
            uids = [c["uid"] for c in cleanup_result["candidates"]]
            await call_tool("execute_clean_batch", uids=uids)
            return "✅ Cleanup complete!"
        else:
            return "❌ Cancelled."
```

### Response Format

All time-boxed tools return:

```json
{
  "status": "partial",          // or "complete"
  "has_more": true,             // false when done
  "candidates": [...],          // this batch's results
  "continuation_state": "...",  // pass to next call (JSON string)
  "time_limit_reached": true,   // why this batch ended
  "processed_count": 45         // emails processed so far
}
```

### Anti-Patterns (FORBIDDEN)

❌ **Prompting user after each batch**:
```python
# WRONG - User gets prompted every 5 seconds!
while has_more:
    result = quick_clean_inbox(...)
    show_to_user(result)      # BAD: partial results
    user_approves()           # BAD: approval per batch
```

❌ **Running loop in orchestrator instead of subagent**:
```python
# WRONG - Orchestrator should delegate, not loop
async def secretary(request):
    while has_more:
        result = quick_clean_inbox(...)  # Should be in subagent
```

✅ **Correct: Subagent loops, orchestrator approves once**:
```python
# RIGHT
subagent_result = await bulk_cleanup_agent()  # Runs full loop
user_approves(subagent_result)                # Single prompt
execute_clean_batch(subagent_result["uids"])  # Execute once
```

### Tools Using This Pattern

| Tool | Purpose | Continuation Field |
|------|---------|-------------------|
| `quick_clean_inbox` | Identify cleanup candidates | `continuation_state` |
| `triage_priority_emails` | Find high-priority emails | `continuation_state` |
| `triage_remaining_emails` | Process remaining emails | `continuation_state` |
| `execute_clean_batch` | Execute approved cleanup | N/A (single call) |
```

## 📚 Best Practices Summary

1. **✅ DO**: Always confirm mutations (send, delete, move)
2. **✅ DO**: Use signals to guide prioritization, not hardcode rules
3. **✅ DO**: Respect timezone and working_hours in all scheduling
4. **✅ DO**: Show drafts before sending
5. **✅ DO**: Provide citations for information from emails
6. **❌ DON'T**: Send emails without user approval
7. **❌ DON'T**: Delete or move emails without confirmation
8. **❌ DON'T**: Ignore VIP sender signals
9. **❌ DON'T**: Schedule meetings outside working hours without asking
10. **❌ DON'T**: Make assumptions about priority without checking signals

---

**Remember**: These tools make AI assistants powerful. The safety patterns make them trustworthy. Both are required for a great user experience.

See [Use Cases](./use-cases) for complete workflow examples.
