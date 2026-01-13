<!-- Refactored embeddings docs generated 2026-01-13 -->

# Migration

## Changing embedding dimensions

If you need to change dimensions after initial sync (e.g., 768 → 3072):

```bash
# 1. Stop the engine
docker compose stop engine

# 2. Drop the embeddings table
docker compose exec postgres psql -U secretary -d secretary -c "DROP TABLE IF EXISTS email_embeddings;"

# 3. Update config.yaml (e.g., dimensions: 3072)

# 4. Restart engine - table recreates automatically
docker compose up -d engine
```

::: warning Re-embedding required
This will re-embed **all** emails from scratch.
:::

## Switching providers

Even if dimensions match, different models typically produce incompatible vectors.
Assume you must re-embed when changing model/provider unless you explicitly guarantee compatibility.
