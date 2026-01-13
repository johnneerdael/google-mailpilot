<!-- Split roadmap docs generated 2026-01-13 -->

# Feature audit — Calendar

## 5. Calendar — viewing

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Week view | ✅ Implemented | `calendar.py`: Default view with week offset navigation |
| Day view | ❌ Missing | No single-day view |
| Month view | ❌ Missing | No month grid view |
| Agenda/list view | ❌ Missing | No agenda-style list |
| Event detail view | 🟡 Partial | Events shown in grid; no click-to-expand detail modal |
| Multiple calendars toggle | ❌ Missing | Shows all calendars; no individual toggle |
| Timezone display | 🟡 Partial | Uses configured timezone; no secondary timezone |
| Working hours shading | ❌ Missing | No visual distinction for working hours |
| Free/busy overlay | ❌ Missing | No availability visualization in calendar grid |

**Category Score**: 2/9 (22%)

---

## 6. Calendar — event management

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Create event | ✅ Implemented | `calendar.py`: `POST /api/calendar/event` with form |
| Edit event | ❌ Missing | No edit UI; Engine API supports it |
| Delete event | ❌ Missing | No delete button in UI; Engine API supports it |
| Recurring events | ❌ Missing | No recurrence UI |
| Attendees management | 🟡 Partial | Can add attendees on create; no edit/remove |
| RSVP status display | ❌ Missing | No attendee response status shown |
| Conference link creation | 🟡 Partial | `meeting_type` field exists; display unclear |
| Location field | ✅ Implemented | Location input in create form |
| Reminders/notifications | ❌ Missing | No reminder settings in UI |

**Category Score**: 3/9 (33%)

---

## 7. Calendar — scheduling

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Availability lookup | ✅ Implemented | `calendar.py`: `/calendar/availability` widget |
| Find a time UI | ❌ Missing | No slot suggestion interface |
| Propose new times | ❌ Missing | No alternative time proposal flow |
| Meeting invite accept/decline | ✅ Implemented | `calendar.py`: `POST /api/calendar/respond/{event_id}` |
| Timezone-aware suggestions | 🟡 Partial | Uses config timezone; no recipient timezone consideration |
| Scheduling links (Calendly-like) | ❌ Missing | No public booking page |

**Category Score**: 2.5/6 (42%)
