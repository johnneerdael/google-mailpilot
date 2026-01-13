<!-- Refactored docs generated 2026-01-13 -->

# API endpoints

## HTML endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to `/inbox` |
| `/inbox` | GET | Inbox view |
| `/inbox?folder=FOLDER` | GET | Specific folder |
| `/thread/<id>` | GET | Thread view |
| `/search` | GET/POST | Search interface |
| `/chat` | GET/POST | AI chat |
| `/settings` | GET/POST | User settings |

## JSON API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/emails` | GET | List emails (JSON) |
| `/api/email/<uid>` | GET | Email details (JSON) |
| `/api/search` | POST | Search emails (JSON) |
| `/api/folders` | GET | List folders (JSON) |

## HTMX partials

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/partials/email-list` | GET | Email list fragment |
| `/partials/email-row/<uid>` | GET | Single email row |
| `/partials/thread/<id>` | GET | Thread fragment |

## CSRF and request expectations

- All forms include CSRF tokens.
- API endpoints require either:
  - a session cookie, or
  - `X-Requested-With: XMLHttpRequest` header.
