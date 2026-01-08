# Google Workspace Secretary: Use Cases & Workflows

This document outlines the high-level workflows that the Google Workspace Secretary MCP enables for AI agents. By combining Gmail and Calendar tools, the server acts as a high-performance executive assistant.

## 1. The Monday Morning Triage
**Goal**: Get a structured overview of the week and prioritize the inbox.

**Workflow**:
1. **Inbox Sweep**: The agent uses `get_unread_messages` and `gmail_search(query="is:unread")` to identify high-priority emails.
2. **Calendar Sync**: The agent calls `list_calendar_events` for the current week to identify busy blocks and deadlines.
3. **Draft Briefing**: The agent summarizes the top 5 urgent emails and highlights any calendar conflicts (e.g., "You have a meeting at 10 AM, but an urgent report was requested at 9:30 AM").
4. **Action**: The agent proposes moving low-priority emails to `Secretary/Newsletter` and flagging `Secretary/Priority` items.

## 2. The Travel & Logistics Coordinator
**Goal**: Automatically extract travel details and ensure they are on the calendar.

**Workflow**:
1. **Search**: The agent searches for recent keywords like "Confirmation", "Flight", "Hotel", or "Reservation".
2. **Deep Read**: The agent uses `get_email_details` or `get_attachment_content` (for PDF receipts) to extract dates, flight numbers, and addresses.
3. **Calendar Check**: The agent uses `get_calendar_availability` to see if the travel times are free.
4. **Event Creation**: The agent calls `create_calendar_event` with the extracted details, including the confirmation number in the description and the hotel address in the location field.

## 3. The Busy-Day Gatekeeper
**Goal**: Manage meeting invites and protect the user's focus time.

**Workflow**:
1. **Invite Detection**: The agent uses `gmail_search(query="label:Secretary/Calendar")` or parses incoming invites.
2. **Availability Logic**:
    - If the time is free: Call `process_meeting_invite(availability_mode="business_hours")` to draft an "Accept" reply.
    - If there is a conflict: The agent identifies the conflicting event and drafts a "Decline" or "Request Reschedule" reply.
3. **Buffer Management**: The agent identifies "back-to-back" days and suggests moving meetings to create breathing room.

## 4. Newsletter & Intelligence Curator
**Goal**: Summarize long-form content and keep the inbox clean.

**Workflow**:
1. **Filter**: The agent identifies newsletters (e.g., using `from:substack.com` or `label:Secretary/Newsletter`).
2. **Summarize**: The agent fetches the full content of the 3 most recent newsletters.
3. **Bulletins**: The agent creates a single "Intelligence Bulletin" email draft for the user, summarizing the key takeaways from all three, then marks the originals as read.

## 5. The "Waiting For" Nudger
**Goal**: Track outgoing requests and ensure nothing falls through the cracks.

**Workflow**:
1. **Sent Items Search**: The agent searches `from:me` emails containing questions or requests.
2. **Thread Analysis**: The agent uses `gmail_get_thread` to see if a reply has been received.
3. **Nudge Suggestion**: If no reply has been received in >48 hours, the agent creates a draft "Gentle Follow-up" and alerts the user.
