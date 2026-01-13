<!-- Refactored embeddings docs generated 2026-01-13 -->

# Configuration reference

```yaml
database:
  backend: postgres

  postgres:
    host: localhost
    port: 5432
    database: secretary
    user: secretary
    password: secretarypass
    ssl_mode: disable  # disable, require, verify-ca, verify-full

  embeddings:
    enabled: true
    provider: gemini         # gemini | cohere | openai_compat
    fallback_provider: ""    # optional failover on rate limit
    endpoint: ""             # required for openai_compat
    model: ""                # provider-specific
    api_key: ""              # openai_compat/cohere
    dimensions: 3072
    batch_size: 100

    # Cohere-specific
    input_type: search_document  # search_document | search_query
    truncate: END                # NONE | START | END

    # Gemini-specific
    gemini_api_key: ""
    gemini_model: text-embedding-004
    task_type: RETRIEVAL_DOCUMENT
```

## Environment variables

```bash
EMBEDDINGS_PROVIDER=cohere
EMBEDDINGS_API_KEY=your-key
EMBEDDINGS_API_BASE=https://api.openai.com/v1
EMBEDDINGS_MODEL=text-embedding-3-small

COHERE_API_KEY=your-cohere-key
GEMINI_API_KEY=your-gemini-key
```
