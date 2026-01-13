<!-- Split roadmap docs generated 2026-01-13 -->

# Feature audit — UX, settings, security, offline

## 8. Contacts & recipients

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Contacts browser | ❌ Missing | No contacts page or API |
| Recent recipients | ❌ Missing | No recent address tracking |
| Contact card popover | ❌ Missing | No sender info on click |
| Groups/distribution lists | ❌ Missing | No group management |
| Recipient autocomplete | ❌ Missing | No typeahead in compose |

**Category Score**: 0/5 (0%)

---

## 10. Notifications & alerts

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| In-app toast notifications | ❌ Missing | No toast component; flash messages unclear |
| Browser notifications | ❌ Missing | No Notification API integration |
| New mail badge/count | 🟡 Partial | Stats badges exist; no real-time update |
| Calendar reminders | ❌ Missing | No browser reminder notifications |
| Error banners | 🟡 Partial | Some error states handled; no global error banner |

**Category Score**: 1/5 (20%)

---

## 11. Settings & preferences

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Settings page | ✅ Implemented | `settings.py`: GET `/settings` with multiple partials |
| VIP senders config | ✅ Implemented | `settings_vips.html` partial |
| Working hours display | ✅ Implemented | `settings_working_hours.html` partial |
| Identity info | ✅ Implemented | `settings_identity.html` partial |
| AI/analysis settings | ✅ Implemented | `settings_ai.html` partial |
| Edit settings | ❌ Missing | Read-only display; no edit forms |
| Theme/dark mode toggle | ❌ Missing | No theme switcher |
| Display density | ❌ Missing | No compact/comfortable toggle |
| Notification preferences | ❌ Missing | No notification settings |
| Keyboard shortcuts toggle | ❌ Missing | No shortcuts config |

**Category Score**: 5/10 (50%)

---

## 12. Keyboard shortcuts & power user

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| List navigation (j/k) | ❌ Missing | No keyboard handlers in JS |
| Action shortcuts (e/r/a/f) | ❌ Missing | No keybindings |
| Search focus (/) | ❌ Missing | No focus shortcut |
| Command palette (Cmd-K) | ❌ Missing | No command palette component |
| Undo shortcut (Cmd-Z) | ❌ Missing | No undo system |
| Shortcuts help modal | ❌ Missing | No help documentation |

**Category Score**: 0/6 (0%)

---

## 13. Mobile/responsive patterns

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Responsive layout | 🟡 Partial | Some responsive CSS; not fully optimized |
| Collapsible sidebar | ❌ Missing | No mobile sidebar toggle |
| Touch-friendly targets | ❌ Missing | No touch gesture support |
| Swipe actions | ❌ Missing | No swipe to archive/delete |
| Mobile compose UX | ❌ Missing | Same form as desktop |

**Category Score**: 0.5/5 (10%)

---

## 14. Offline & sync

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| Sync status indicator | ❌ Missing | No "last synced" display |
| Offline reading cache | ❌ Missing | No service worker |
| Offline compose queue | ❌ Missing | No offline support |
| Conflict handling | ❌ Missing | No multi-device sync |

**Category Score**: 0/4 (0%)

---

## 15. Security & privacy

| Feature | Status | Evidence / Notes |
|---------|--------|------------------|
| CSRF protection | ✅ Implemented | FastAPI middleware; forms have protection |
| HTML sanitization | ✅ Implemented | `thread.py`: Comprehensive sanitization |
| Authentication enforcement | ✅ Implemented | `require_auth` on all routes (v4.4.3) |
| Remote image blocking | ❌ Missing | No "load images" toggle |
| Phishing warnings | ❌ Missing | No suspicious sender detection |
| Action confirmations | ❌ Missing | No "are you sure?" dialogs |
| Audit log | ❌ Missing | No action history UI |

**Category Score**: 3/7 (43%)
