<!-- Refactored embeddings docs generated 2026-01-13 -->

# Database schema

```sql
CREATE TABLE email_embeddings (
    id SERIAL PRIMARY KEY,
    email_uid INTEGER NOT NULL,
    folder VARCHAR(255) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    embedding vector(3072),
    model VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(email_uid, folder)
);

CREATE INDEX ON email_embeddings
    USING hnsw (embedding vector_ip_ops)
    WITH (m = 16, ef_construction = 64);
```

::: tip Why inner product?
Vectors are L2-normalized, making inner product equivalent to cosine similarity but faster.
:::
