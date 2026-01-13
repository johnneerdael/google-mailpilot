# Calendar Tools

Calendar management and scheduling tools.

::: tip Timezone-Aware
All calendar operations respect your configured `timezone` and `working_hours` from config.yaml.
:::

## check_calendar

Check calendar availability in a time range.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `time_min` | string | Yes | Start time (ISO 8601 format) |
| `time_max` | string | Yes | End time (ISO 8601 format) |

::: tip ISO 8601 Format Required
Use ISO 8601 format with timezone offset:
- ✅ `2026-01-09T09:00:00-08:00`
- ❌ `2026-01-09 9am` or `09:00`
:::

**Example:**
```json
{
  "time_min": "2026-01-09T09:00:00-08:00",
  "time_max": "2026-01-09T17:00:00-08:00"
}
```

**Returns:**
```json
{
  "events": [
    {
      "summary": "Team Standup",
      "start": "2026-01-09T09:30:00-08:00",
      "end": "2026-01-09T10:00:00-08:00",
      "attendees": ["team@company.com"]
    },
    {
      "summary": "1:1 with Manager",
      "start": "2026-01-09T14:00:00-08:00",
      "end": "2026-01-09T14:30:00-08:00",
      "attendees": ["manager@company.com"]
    }
  ],
  "free_slots": [
    {"start": "2026-01-09T10:00:00-08:00", "end": "2026-01-09T14:00:00-08:00"},
    {"start": "2026-01-09T14:30:00-08:00", "end": "2026-01-09T17:00:00-08:00"}
  ]
}
```

**Classification:** Read-only ✅

## list_calendar_events

List calendar events in a date range.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `time_min` | string | Yes | Start time (ISO 8601 format, e.g., 2026-01-09T00:00:00-08:00) |
| `time_max` | string | Yes | End time (ISO 8601 format) |
| `calendar_id` | string | No | Calendar ID (default: "primary") |

::: tip ISO 8601 Format Required
All calendar operations require ISO 8601 format with timezone offset:
- ✅ Correct: `2026-01-09T09:00:00-08:00` (9 AM Pacific Time)
- ❌ Incorrect: `2026-01-09` or `09:00`
:::

**Returns:**
```json
{
  "events": [
    {
      "id": "event_123",
      "summary": "Q1 Planning",
      "start": "2026-01-10T10:00:00-08:00",
      "end": "2026-01-10T12:00:00-08:00",
      "location": "Conference Room A",
      "attendees": ["team@company.com"],
      "status": "confirmed"
    }
  ],
  "total_events": 5
}
```

**Classification:** Read-only ✅

**Example:**
```json
{
  "time_min": "2026-01-09T00:00:00-08:00",
  "time_max": "2026-01-09T23:59:59-08:00"
}
```

## suggest_reschedule

Find alternative meeting times within working hours.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thread_id` | string | Yes | Email thread with original invite |
| `suggested_date` | string | Yes | Target date (YYYY-MM-DD) |
| `duration_minutes` | number | No | Meeting duration (default: 30) |

**Returns:**
```json
{
  "original_time": "2026-01-09T08:00:00-08:00",
  "suggested_slots": [
    {
      "start": "2026-01-10T10:00:00-08:00",
      "end": "2026-01-10T10:30:00-08:00",
      "conflicts": []
    },
    {
      "start": "2026-01-10T14:00:00-08:00",
      "end": "2026-01-10T14:30:00-08:00",
      "conflicts": []
    },
    {
      "start": "2026-01-10T15:30:00-08:00",
      "end": "2026-01-10T16:00:00-08:00",
      "conflicts": []
    }
  ],
  "working_hours": {
    "start": "09:00",
    "end": "17:00",
    "timezone": "America/Los_Angeles"
  }
}
```

::: tip Working Hours Respected
Suggestions only include times within your configured `working_hours` on `workdays`. If the original meeting was outside working hours, suggestions will be within working hours unless the user explicitly requests otherwise.
:::

**Classification:** Staging ✅ (suggestions only, no calendar changes)

## create_calendar_event

Create a new calendar event.

::: danger Mutation Tool
**Requires user confirmation before creating.** Show event details and ask for approval.
:::

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `summary` | string | Yes | Event title |
| `start_time` | string | Yes | Start time (ISO 8601 format) |
| `end_time` | string | Yes | End time (ISO 8601 format) |
| `description` | string | No | Event description |
| `location` | string | No | Event location |
| `calendar_id` | string | No | Calendar ID (default: "primary") |
| `meeting_type` | string | No | Set to "google_meet" to add video conferencing |

**Example request:**
```json
{
  "summary": "Project Review",
  "start_time": "2026-01-10T14:00:00-08:00",
  "end_time": "2026-01-10T15:00:00-08:00",
  "description": "Quarterly project status review",
  "location": "Conference Room A",
  "attendees": ["team@company.com", "manager@company.com"],
  "meeting_type": "google_meet"
}
```

**Classification:** Mutation 🔴 (requires user confirmation)

## process_meeting_invite

Accept or decline a meeting invitation.

::: danger Mutation Tool
**Requires user confirmation.** Even for meetings outside working hours—the user may have exceptions (investor calls, international meetings, etc.).
:::

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_id` | string | Yes | Calendar event ID |
| `response` | string | Yes | `accept`, `decline`, or `tentative` |
| `message` | string | No | Optional response message |

**Working Hours Check:**
If the meeting is outside configured working hours, present options:
```
This meeting is scheduled for 8 PM (outside your working hours: 9 AM - 6 PM).

Options:
1. Accept as-is (special circumstances)
2. Suggest alternative times within working hours
3. Decline politely
```

**Classification:** Mutation 🔴 (requires user confirmation)

## respond_to_meeting

Respond to a meeting invitation (accept, decline, or tentative).

::: danger Mutation Tool
**Requires user confirmation.** Even for meetings outside working hours—the user may have exceptions (investor calls, international meetings, etc.).
:::

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_id` | string | Yes | Calendar event ID |
| `calendar_id` | string | No | Calendar ID (default: "primary") |
| `response` | string | Yes | `accepted`, `declined`, or `tentative` |

**Working Hours Check:**
If the meeting is outside configured working hours, present options:
```
This meeting is scheduled for 8 PM (outside your working hours: 9 AM - 6 PM).

Options:
1. Accept as-is (special circumstances)
2. Suggest alternative times within working hours
3. Decline politely
```

**Classification:** Mutation 🔴 (requires user confirmation)

---

**Next:** [Intelligence Tools](./intelligence) | [Email Tools](./email)
