<!-- Split roadmap docs generated 2026-01-13 -->

# Feature audit — Email & search

## 1. Email reading & navigation

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Inbox list with summaries | ✅ Implemented | `inbox.py`: pagination, folder filter, unread filter. Shows from, subject, preview, date, unread badge, attachment icon |
| Message detail view | ✅ Implemented | `thread.py`: Full message content, sanitized HTML, plain→HTML conversion |
| Thread/conversation view | ✅ Implemented | `thread.py`: Groups messages by thread, shows all in conversation |
| Next/previous navigation | ❌ Missing | No nav links in thread view; must return to list |
| Unread/read visual styling | ✅ Implemented | `is_unread` flag passed to template, CSS styling present |
| Multi-select in list | ❌ Missing | No checkboxes in inbox template |
| Bulk action toolbar | 🟡 Partial | `bulk.py` API exists but no UI toolbar; requires JS integration |
| Pagination | ✅ Implemented | `inbox.py`: `page`, `per_page` params; pagination controls in template |
| Infinite scroll | ❌ Missing | Uses traditional pagination only |
| Folder/label sidebar | ✅ Implemented | Sidebar in `base.html` with folder list |
| Star/flag indicators | ❌ Missing | No star/flag support in UI or API |
| HTML email sanitization | ✅ Implemented | `thread.py`: Removes script, style, on* handlers, sanitizes URLs |
| Inline image display | 🟡 Partial | Displays if embedded; no "load remote images" toggle |
| Quoted text collapsing | ❌ Missing | Full quoted text shown; no collapse UI |
| Attachment display | ✅ Implemented | Shows attachment list with filename, size; download links |

**Category Score**: 9/15 (60%)

---

## 2. Email composition & sending

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Compose new email | ✅ Implemented | `compose.py`: GET `/compose`, form with to/cc/bcc/subject/body |
| Reply | ✅ Implemented | `compose.py`: `reply_to` param prefills recipient + quoted text |
| Reply All | ✅ Implemented | `compose.py`: `reply_all` param includes all recipients |
| Forward | ✅ Implemented | `compose.py`: `forward` param prefills body with forwarded content |
| Draft autosave | 🟡 Partial | `POST /api/email/draft` exists; no JS autosave timer |
| Rich text editor | ❌ Missing | Plain textarea only; no formatting toolbar |
| Attach files | ❌ Missing | No file upload in compose form |
| Recipient autocomplete | ❌ Missing | No typeahead/contacts API integration |
| Send email | ✅ Implemented | `POST /api/email/send` with success/error handling |
| Undo send | ❌ Missing | No delayed send queue |
| Schedule send | ❌ Missing | No datetime picker or scheduling |
| Signature management | ❌ Missing | No signature settings or auto-insertion |
| From/alias selection | ❌ Missing | No alias picker if multiple identities |
| Address validation warnings | ❌ Missing | No "missing subject" or "forgot attachment" warnings |
| Templates/canned responses | ❌ Missing | No template insertion feature |

**Category Score**: 6/15 (40%)

---

## 3. Email organization & management

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Archive action | ✅ Implemented | `actions.py` + `bulk.py`: Move to Archive |
| Delete action | ✅ Implemented | `actions.py` + `bulk.py`: Move to Trash |
| Move to folder | ✅ Implemented | `actions.py`: `/api/email/move` with destination |
| Apply/remove labels | ✅ Implemented | `actions.py`: `/api/email/labels` with add/remove/set |
| Mark read/unread | ✅ Implemented | `actions.py` + `bulk.py`: Toggle read state |
| Mark as spam | ❌ Missing | No spam action in UI |
| Mute thread | ❌ Missing | No mute functionality |
| Snooze | ❌ Missing | No snooze until later feature |
| Undo toast | ❌ Missing | No undo mechanism after actions |
| Filters/rules UI | ❌ Missing | No filter management in settings |
| Follow-up reminders | ❌ Missing | No "remind me" or "waiting for reply" |

**Category Score**: 6/11 (55%)

---

## 4. Search & discovery

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Search bar in header | ✅ Implemented | `search.py`: GET `/search` with query input |
| Basic keyword search | ✅ Implemented | Searches subject, body, from/to |
| Advanced filters UI | ✅ Implemented | `search.py`: from, date_from, date_to, has_attachments, is_unread |
| Search operator parsing | ❌ Missing | No `from:`, `to:`, `subject:` operator syntax |
| Search results list | ✅ Implemented | Results displayed with pagination |
| Semantic/AI search | ✅ Implemented | `search.py`: `mode=semantic` toggle, uses embeddings |
| Saved searches | ✅ Implemented | `POST /search/save`, `DELETE /search/saved/{id}` (in-memory) |
| Search suggestions | ✅ Implemented | `GET /search/suggestions` for autocomplete |
| Search within thread | ❌ Missing | No Ctrl+F style in-thread search |
| Attachment search | 🟡 Partial | `has_attachments` filter exists; no filename search |

**Category Score**: 8/10 (80%)

---

## 9. Attachments & files

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Attachment list with download | ✅ Implemented | `thread.py`: Shows attachments with download links |
| Inline preview (PDF/image) | ❌ Missing | Download only; no in-browser preview |
| Attachment upload in compose | ❌ Missing | No file upload support |
| Virus/malware warnings | ❌ Missing | No security scanning indicators |
| Cloud storage integration | ❌ Missing | No Drive/Dropbox integration |
| Attachment search | 🟡 Partial | `has_attachments` filter; no filename search |

**Category Score**: 1.5/6 (25%)
