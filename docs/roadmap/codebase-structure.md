<!-- Split roadmap docs generated 2026-01-13 -->

# Codebase structure

## Routes (13 files)

- `inbox.py` — Email list with pagination
- `thread.py` — Thread/message detail view
- `compose.py` — Email composition (new/reply/forward)
- `search.py` — Keyword + semantic search
- `calendar.py` — Week view + event creation
- `settings.py` — Read-only config display
- `bulk.py` — Bulk email operations
- `actions.py` — Single email actions
- `dashboard.py` — Priority inbox + stats
- `chat.py` — AI chat interface
- `analysis.py` — Email analysis sidebar
- `notifications.py` — Notification endpoints
- `__init__.py` — Router registration

## Templates (22 files)

- Core: `base.html`, `inbox.html`, `thread.html`, `search.html`, `compose.html`, `calendar.html`, `dashboard.html`, `settings.html`, `chat.html`
- Auth: `auth/login.html`
- Partials: `email_list`, `email_widget`, `stats_badges`, `analysis_sidebar`, `availability_widget`, `saved_searches`, `search_suggestions`, `settings_*`

## Static JS (1 file)

- `app.js` — Minimal (~29 lines): Alpine.js collapse directive + HTMX loading state
