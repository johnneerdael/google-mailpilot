<!-- Refactored docs generated 2026-01-13 -->

# Customization

## Theming

Override CSS variables in `/static/css/custom.css`:

```css
:root {
    --primary-color: #4A90D9;
    --background-color: #ffffff;
    --text-color: #333333;
    --border-color: #e0e0e0;
    --hover-color: #f5f5f5;
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
    :root {
        --background-color: #1a1a1a;
        --text-color: #e0e0e0;
        --border-color: #333333;
        --hover-color: #2a2a2a;
    }
}
```

## Templates

Templates are located in `workspace_secretary/web/templates/`:

```
templates/
├── base.html           # Base layout
├── inbox.html          # Inbox view
├── thread.html         # Thread view
├── search.html         # Search page
├── chat.html           # AI chat
├── settings.html       # Settings page
└── partials/
    ├── email-list.html
    ├── email-row.html
    └── nav.html
```
