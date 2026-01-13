<!-- Refactored docs generated 2026-01-13 -->

# Settings & notifications

Settings are available at `/settings`.

## Account

- View connected email account
- Check sync status
- View folder list

## Display

- Emails per page (10, 25, 50, 100)
- Default folder
- Date format

## Notifications

- Enable browser notifications
- Notification sound
- Quiet hours

### Browser notifications

1. Click the bell icon in navigation
2. Grant permission when prompted
3. Receive alerts for new unread emails

```javascript
// Notification example
{
  title: "New email from Sarah",
  body: "Q4 Budget Review - Please approve by EOD",
  icon: "/static/icon.png"
}
```
