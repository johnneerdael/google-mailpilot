<!-- Refactored embeddings docs generated 2026-01-13 -->

# Quick start

## 1) Enable PostgreSQL with pgvector

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: secretary
      POSTGRES_USER: secretary
      POSTGRES_PASSWORD: secretarypass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

## 2) Configure embeddings

```yaml
database:
  backend: postgres
  postgres:
    host: postgres
    port: 5432
    database: secretary
    user: secretary
    password: secretarypass

  embeddings:
    enabled: true
    provider: gemini
    gemini_api_key: ${GEMINI_API_KEY}
    gemini_model: text-embedding-004
    dimensions: 3072
    batch_size: 100
    task_type: RETRIEVAL_DOCUMENT
```

## 3) Start the server

```bash
docker compose up -d
```

Embeddings are generated automatically during email sync.
