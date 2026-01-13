<!-- Refactored embeddings docs generated 2026-01-13 -->

# Performance tuning

## HNSW index tuning

```sql
CREATE INDEX ON email_embeddings
    USING hnsw (embedding vector_ip_ops)
    WITH (m = 32, ef_construction = 128);

SET hnsw.ef_search = 100;
```

## Incremental sync

Only new emails are embedded during sync. A `content_hash` can prevent re-embedding unchanged emails.
