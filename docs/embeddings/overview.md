<!-- Refactored embeddings docs generated 2026-01-13 -->

# Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Email Text    │────▶│ Embeddings API   │────▶│ Vector (3072d)  │
│ "Meeting moved" │     │ (Gemini default) │     │ [0.12, -0.34,…] │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                          │
                              L2 Normalized ──────────────┤
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Search Query   │────▶│ Embeddings API   │────▶│  Inner Product  │
│ "schedule change"│    │  + Hard Filters  │     │     Search      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Requirements

- PostgreSQL with pgvector extension
- An embeddings provider (Gemini recommended; Cohere/OpenAI-compatible also supported)

## Recommended approach

Use **hard filters first, then semantic ranking** (to avoid “vector drift”):

```sql
SELECT *
FROM emails e
JOIN email_embeddings emb ON ...
WHERE e.from_addr ILIKE '%john%'
  AND e.date >= '2024-01-01'
ORDER BY emb.embedding <#> query_vec
LIMIT 10;
```
