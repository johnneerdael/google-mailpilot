# Semantic Search

AI-powered semantic search allows you to find emails by **meaning** rather than exact keywords. Instead of searching for "invoice", you can ask "find emails about money owed to us" and get relevant results.

::: tip When to Use Semantic Search
- **Conceptual queries**: "emails about project delays", "discussions about budget concerns"
- **Finding related context**: Get similar emails to draft better replies
- **Vague recall**: "that email from last month about the thing we discussed"

For exact matches (sender, date, specific phrase), use regular `search_emails`.
:::

## Prerequisites

Semantic search requires:

1. **PostgreSQL with pgvector** - Vector similarity search extension
2. **OpenAI-compatible embeddings API** - Converts text to vectors
3. **Background sync** - Embeddings are generated asynchronously

## Setup

### 1. Deploy with PostgreSQL

Use the PostgreSQL-enabled Docker Compose:

```bash
# Create .env file with secrets
cat > .env << 'EOF'
POSTGRES_PASSWORD=your-secure-password
OPENAI_API_KEY=sk-your-openai-key
EOF

# Start services
docker compose -f docker-compose.postgres.yml up -d
```

Or add PostgreSQL to your existing setup:

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: secretary
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: secretary
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U secretary"]
      interval: 10s
      timeout: 5s
      retries: 5

  workspace-secretary:
    image: ghcr.io/johnneerdael/google-mailpilot:latest
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./config:/app/config
    environment:
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    command: ["--config", "/app/config/config.yaml", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]

volumes:
  postgres_data:
```

### 2. Configure Embeddings

Update `config.yaml` (Gemini recommended):

```yaml
database:
  backend: postgres
  
  postgres:
    host: postgres          # Docker service name, or localhost
    port: 5432
    database: secretary
    user: secretary
    password: ${POSTGRES_PASSWORD}
    ssl_mode: prefer
  
  embeddings:
    enabled: true
    provider: gemini
    gemini_api_key: ${GEMINI_API_KEY}
    gemini_model: text-embedding-004
    dimensions: 3072        # 768, 1536, or 3072 available
    batch_size: 100         # Texts per API call
    task_type: RETRIEVAL_DOCUMENT
```

### 3. Alternative Embeddings Providers

Any OpenAI-compatible endpoint works:

```yaml
# Azure OpenAI
embeddings:
  enabled: true
  endpoint: https://your-resource.openai.azure.com/openai/deployments/your-deployment/embeddings?api-version=2024-02-01
  model: text-embedding-3-small
  api_key: ${AZURE_OPENAI_KEY}

# Local Ollama
embeddings:
  enabled: true
  endpoint: http://ollama:11434/api/embeddings
  model: nomic-embed-text
  api_key: ""              # Ollama doesn't need a key
  dimensions: 768          # Match Ollama model output

# vLLM / LocalAI / LiteLLM
embeddings:
  enabled: true
  endpoint: http://localhost:8080/v1/embeddings
  model: BAAI/bge-small-en-v1.5
  api_key: ${LOCAL_API_KEY}
  dimensions: 384
```

### 4. Cohere (Native SDK)

Cohere's embed-v4 model offers a 1.28M token context window and optimized retrieval via `input_type` parameter.

```yaml
embeddings:
  enabled: true
  provider: cohere
  model: embed-v4.0
  api_key: ${COHERE_API_KEY}
  input_type: search_document
  dimensions: 1536
  batch_size: 96
```

**Configuration options:**

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `openai_compat` | Set to `cohere` for native SDK |
| `model` | - | `embed-v4.0` recommended |
| `input_type` | `search_document` | Used for indexing emails |
| `batch_size` | `96` | Cohere's max per API call |
| `truncate` | `END` | Server-side truncation: `NONE`, `START`, `END` |

::: tip Automatic Query Optimization
When searching, the system automatically switches to `input_type: search_query` for better retrieval accuracy. You don't need to configure this—just set `search_document` for indexing.
:::

**Free tier**: 1,000 API calls/month limit. Consider Gemini for higher free tier limits.

## Available Tools

When semantic search is enabled, three additional tools become available:

### `semantic_search_emails`

Search emails by meaning, not keywords.

```
AI: "Find emails about project timeline concerns"

→ Returns emails discussing:
  - "We might miss the Q4 deadline"
  - "Schedule is getting tight"
  - "Need to push back the launch date"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural language search query |
| `folder` | string | "INBOX" | Folder to search |
| `limit` | int | 20 | Maximum results |
| `similarity_threshold` | float | 0.7 | Minimum similarity (0.0-1.0) |

**Example Response:**

```json
{
  "results": [
    {
      "uid": 12345,
      "subject": "Re: Q4 Launch Planning",
      "from": "pm@company.com",
      "date": "2026-01-07T14:30:00Z",
      "similarity": 0.89,
      "snippet": "I'm concerned about our current timeline..."
    }
  ],
  "query": "project timeline concerns",
  "total_results": 3
}
```

### `find_related_emails`

Find emails similar to a specific email. Great for gathering context before drafting replies.

```
AI: "Find emails related to the one from Sarah about the budget"

→ Returns other emails in the same conversation thread
→ Plus emails with similar topics from other senders
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uid` | int | required | UID of reference email |
| `folder` | string | "INBOX" | Folder containing reference email |
| `limit` | int | 10 | Maximum results |
| `similarity_threshold` | float | 0.75 | Minimum similarity |

### `get_embedding_status`

Check the health of the embeddings system.

```json
{
  "semantic_search_available": true,
  "database_backend": "postgres",
  "embeddings_configured": true,
  "embeddings_model": "text-embedding-3-small",
  "embeddings_endpoint": "https://api.openai.com/v1/embeddings",
  "database_supports_embeddings": true,
  "inbox_emails_without_embeddings": 45
}
```

Use this to troubleshoot if semantic search isn't working.

## How It Works

### Embedding Generation

1. **On email sync**: When new emails arrive, they're stored in PostgreSQL
2. **Background worker**: Periodically processes emails without embeddings
3. **Text preparation**: Subject + body text is cleaned and truncated (~8000 tokens max)
4. **API call**: Text is sent to embeddings endpoint, returns vector
5. **Storage**: Vector stored in `email_embeddings` table with pgvector

### Similarity Search

1. **Query embedding**: Your search query is converted to a vector (with `task_type: RETRIEVAL_QUERY` for Gemini)
2. **Inner product similarity**: pgvector computes `-(query <#> stored)` for L2-normalized vectors
3. **Threshold filter**: Only results above `similarity_threshold` returned
4. **HNSW index**: Approximate nearest neighbor for fast search at scale

### Database Schema

```sql
-- Emails table (simplified)
CREATE TABLE emails (
    uid INTEGER,
    folder VARCHAR(255),
    subject TEXT,
    body TEXT,
    content_hash VARCHAR(64),  -- For tracking embedding freshness
    PRIMARY KEY (uid, folder)
);

-- Embeddings table
CREATE TABLE email_embeddings (
    email_uid INTEGER,
    email_folder VARCHAR(255),
    embedding vector(1536),    -- pgvector type
    model VARCHAR(100),
    content_hash VARCHAR(64),
    created_at TIMESTAMP,
    PRIMARY KEY (email_uid, email_folder)
);

-- HNSW index for fast similarity search (inner product for L2-normalized vectors)
CREATE INDEX idx_embeddings_vector
ON email_embeddings USING hnsw (embedding vector_ip_ops);
```

## Agent Patterns

### Context Gathering Before Reply

```python
# When user asks to reply to an email:
1. Get the email details
2. Call find_related_emails(uid=email_uid) to get context
3. Review related emails for:
   - Previous discussion history
   - Commitments made
   - Key decisions
4. Draft reply with full context
```

### Intelligent Search Routing

```python
# Route to appropriate search based on query:
if has_specific_criteria(query):  # "from:john", "subject:invoice"
    use search_emails()  # Keyword search
else:
    use semantic_search_emails()  # Meaning-based search
```

### Morning Briefing Enhancement

```python
# Enhanced daily briefing:
1. Get standard briefing with email_candidates
2. For high-priority emails, call find_related_emails()
3. Provide context: "Sarah's question relates to 3 previous emails about..."
```

## Troubleshooting

### Semantic search not available

Check `get_embedding_status`:

```
"semantic_search_available": false
```

**Causes:**
- `database.backend` not set to `postgres`
- `database.embeddings.enabled` is `false`
- Missing `api_key` for embeddings
- PostgreSQL not running or unhealthy

### High `inbox_emails_without_embeddings`

Embeddings are generated in background. If count stays high:

1. Check logs for embedding errors
2. Verify API key is valid
3. Check rate limits on embeddings API
4. Ensure PostgreSQL has enough disk space

### Poor search results

**Similarity too low**: Lower `similarity_threshold` (try 0.5)

**Missing relevant emails**: 
- Check if email has embedding (`get_embedding_status`)
- Wait for background sync to complete
- Verify email is in searched folder

**Too many irrelevant results**: Raise `similarity_threshold` (try 0.85)

### Connection errors

```
"error": "Database not initialized or doesn't support embeddings"
```

Check:
- PostgreSQL container is healthy: `docker compose ps`
- pgvector extension installed: `docker exec postgres psql -U secretary -c "SELECT * FROM pg_extension WHERE extname='vector'"`
- Correct connection string in config

## Performance Considerations

| Emails | Index Build | Search Time | Storage |
|--------|-------------|-------------|---------|
| 10,000 | ~30 sec | <100ms | ~60MB |
| 100,000 | ~5 min | <200ms | ~600MB |
| 1,000,000 | ~1 hour | <500ms | ~6GB |

**Tips:**
- HNSW index trades accuracy for speed (default settings are good)
- `batch_size: 100` balances API costs with sync speed
- Consider archiving old emails if storage is a concern

## Fallback Behavior

When semantic search is unavailable, tools gracefully degrade:

- `semantic_search_emails` → Returns error with suggestion to use `search_emails`
- `find_related_emails` → Returns error explaining embedding not found
- `get_embedding_status` → Always works, shows diagnostic info

Regular keyword search (`search_emails`) always works regardless of backend.

## Next Steps

- [Configuration Guide](./configuration) - All database options
- [Agent Patterns](./agents) - Building intelligent workflows
- [MCP Tools Reference](/tools/) - Complete tool documentation
