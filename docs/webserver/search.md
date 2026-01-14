<!-- Refactored docs generated 2026-01-13 -->

# Search

Search is available via the UI at `/search` and via the JSON endpoint at `/api/search`.

## Basic search

Keyword search across subject and body:

```
┌─────────────────────────────────────┐
│ 🔍 Search emails...          [Search] │
└─────────────────────────────────────┘
```

## Advanced filters

Click **Advanced** for detailed filtering:

| Filter | Description | Example |
|--------|-------------|---------|
| From | Sender email/name | `john@company.com` |
| To | Recipient | `me@gmail.com` |
| Subject | Subject keywords | `Q4 Budget` |
| Date Range | Start and end dates | `2026-01-01` to `2026-01-10` |
| Has Attachment | Filter to emails with files | ✓ |
| Unread Only | Filter to unread | ✓ |

## Semantic search (optional)

Toggle **Semantic** for meaning-based search:

```
┌─────────────────────────────────────────────────┐
│ 🔍 budget concerns                    [Semantic ✓] │
└─────────────────────────────────────────────────┘

Results:
• "Q4 Spending Review" (similarity: 89%)
• "Cost overrun in Project X" (similarity: 84%)
• "We need to reduce expenses" (similarity: 78%)
```

Requires embeddings configuration. See our dedicated documentation for more info:: [Embeddings](/embeddings/overview)

## Saved searches

Save frequently-used searches:

1. Enter search criteria
2. Click **Save Search**
3. Name it (e.g., “VIP Unread”)
4. Access it from the **Saved** dropdown
