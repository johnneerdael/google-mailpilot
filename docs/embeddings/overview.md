<!-- Refactored embeddings docs generated 2026-01-13 -->

# Overview

<img width="769" height="338" alt="Screenshot 2026-01-14 at 02 28 58" src="https://github.com/user-attachments/assets/135557f1-485b-42fc-acef-fb3e0f0a977b" />


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
