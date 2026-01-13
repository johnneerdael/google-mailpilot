<!-- Refactored docs generated 2026-01-13 -->

# Web UI basics

The main interface provides: inbox browsing, folders/labels, thread reading, and bulk actions.

## Routes at a glance

- `/` → redirects to `/inbox`
- `/inbox` → inbox view (supports `?folder=`)
- `/thread/<id>` → thread / conversation view

Full endpoint list: [API endpoints](api.md)

## Inbox view (`/inbox`)

The main inbox displays:

| Feature | Description |
|---------|-------------|
| Unread indicators | Bold styling, visual badges |
| Sender & subject | Quick scan with avatars |
| Timestamps | Relative (“2 hours ago”) and absolute |
| Snippets | First line preview |
| Pagination | Configurable page size |

### Folder navigation

Switch between Gmail folders:

- **INBOX** — Primary inbox
- **[Gmail]/Sent Mail** — Sent emails
- **[Gmail]/Drafts** — Draft emails
- **[Gmail]/All Mail** — All archived mail
- **Custom labels** — Your Gmail labels

## Thread view (`/thread/<id>`)

Click an email to view the full conversation:

- **Chronological display** — Oldest to newest
- **Sender avatars** — Visual distinction
- **HTML rendering** — Safe, sanitized HTML
- **Attachments** — Download links
- **Reply/Forward** — Action buttons

## Bulk actions

Select multiple emails with checkboxes:

```
┌──────────────────────────────────────────────────┐
│ ☑ Select All    [Mark Read] [Archive] [Delete]   │
├──────────────────────────────────────────────────┤
│ ☑ Newsletter from Company A                      │
│ ☑ Weekly Digest #234                             │
│ ☐ Important: Q4 Budget Review                    │
│ ☑ Your order has shipped                         │
└──────────────────────────────────────────────────┘
```

Available actions:

- **Mark as Read** — Clear unread status
- **Mark as Unread** — Flag for attention
- **Archive** — Move to All Mail
- **Delete** — Move to Trash
- **Apply Label** — Add Gmail label

::: warning Confirmation Required
All bulk actions require confirmation before executing.
:::

Next: [Search](search.md) · [AI chat](chat.md) · [Settings](settings.md)
