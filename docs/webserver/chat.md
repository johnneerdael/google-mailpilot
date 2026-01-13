<!-- Refactored docs generated 2026-01-13 -->

# AI chat

Interactive assistant at `/chat` for summarization, triage, drafting, and more.

```
┌─────────────────────────────────────────────────┐
│ 🤖 AI Assistant                                 │
├─────────────────────────────────────────────────┤
│ User: Summarize my unread emails                │
│                                                 │
│ Assistant: You have 12 unread emails:           │
│ • 3 from VIP contacts (Sarah, John, CEO)        │
│ • 5 newsletters                                 │
│ • 2 calendar invites                            │
│ • 2 automated notifications                     │
│                                                 │
│ Priority: Sarah’s email about Q4 budget needs   │
│ attention — asking for approval by EOD.         │
├─────────────────────────────────────────────────┤
│ 💬 Ask anything...                      [Send]  │
└─────────────────────────────────────────────────┘
```

## Capabilities

- Summarize emails and threads
- Search by natural language
- Draft replies (requires approval to send)
- Check calendar availability
- Triage and prioritize

## Example prompts

- “What emails need my attention today?”
- “Find emails about the Q4 budget”
- “Draft a reply to Sarah saying I'll review it tomorrow”
- “What meetings do I have this week?”

## Configuration (LLM)

Set the LLM environment variables:

```bash
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o
```

If you see **“AI features unavailable”**, check logs and confirm the API key and base URL.
