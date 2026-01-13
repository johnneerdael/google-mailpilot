<!-- Refactored docs generated 2026-01-13 -->

# Troubleshooting

## Page not loading

Symptom:

```
Connection refused
```

Solutions:

1. Check the container is running: `docker ps`
2. Check logs: `docker logs workspace-secretary`
3. Verify port mapping: `-p 8080:8080`

## AI chat not working

Symptom:

```
AI features unavailable
```

Solutions:

1. Set environment variables:

   ```bash
   LLM_API_BASE=https://api.openai.com/v1
   LLM_API_KEY=sk-your-key
   LLM_MODEL=gpt-4o
   ```

2. Confirm API key is valid
3. Check logs for errors

## Semantic search not working

Symptom:

```
Semantic search unavailable
```

Solutions:

1. Configure embeddings: see [Embeddings](embeddings.md)
2. Set environment variables:

   ```bash
   EMBEDDINGS_PROVIDER=cohere
   EMBEDDINGS_API_KEY=your-key
   ```

3. Ensure PostgreSQL is running with pgvector

## Slow performance

Possible improvements:

1. Increase page size limit carefully
2. Add database indexes
3. Enable connection pooling
4. Use pagination for large folders
