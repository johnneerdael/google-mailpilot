<!-- Refactored docs generated 2026-01-13 -->

# Configuration

## Environment variables

```bash
# Required: Email configuration (via config.yaml)
CONFIG_PATH=/app/config/config.yaml

# Optional: AI Chat (LLM)
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o

# Optional: Semantic Search (Gemini recommended)
EMBEDDINGS_PROVIDER=gemini
EMBEDDINGS_API_KEY=your-gemini-api-key
EMBEDDINGS_MODEL=text-embedding-004

# Optional: Server settings
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_DEBUG=false
```

## Full Docker Compose example (with Postgres + pgvector)

```yaml
services:
  workspace-secretary:
    image: ghcr.io/johnneerdael/gmail-secretary-map:latest
    ports:
      - "8000:8000"  # MCP server
      - "8080:8080"  # Web UI
    volumes:
      - ./config:/app/config
    environment:
      # AI Chat
      - LLM_API_BASE=https://api.openai.com/v1
      - LLM_API_KEY=${OPENAI_API_KEY}
      - LLM_MODEL=gpt-4o

      # Semantic Search (Gemini recommended)
      - EMBEDDINGS_PROVIDER=gemini
      - EMBEDDINGS_API_KEY=${GEMINI_API_KEY}
      - EMBEDDINGS_MODEL=text-embedding-004

      - ENGINE_API_URL=http://127.0.0.1:8001
    depends_on:
      - postgres

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: secretary
      POSTGRES_USER: secretary
      POSTGRES_PASSWORD: secretarypass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```
