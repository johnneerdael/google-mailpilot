<!-- Refactored embeddings docs generated 2026-01-13 -->

# Troubleshooting

## Rate limit (429)

- Reduce `batch_size`
- Configure a fallback provider

## Dimension mismatch

Make sure `dimensions` matches your model output.

## pgvector not found

Use the pgvector image:

```yaml
postgres:
  image: pgvector/pgvector:pg16
```

## Embeddings not generated

Common causes:
- `enabled: false`
- missing API key
- database connectivity issues
- sync not completed
