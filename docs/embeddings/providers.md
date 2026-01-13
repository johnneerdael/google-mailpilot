<!-- Refactored embeddings docs generated 2026-01-13 -->

# Providers

## Decision matrix

| Scenario | Recommended | Why |
|----------|-------------|-----|
| Initial sync (large mailbox) | Gemini Paid (Tier 1+) | Fast throughput, unlimited daily requests |
| Maintenance only | Gemini Free | 1,000 RPD often enough for new mail |
| Cost-sensitive + small mailbox | Gemini Free | Free (but slow for large initial sync) |
| Resilience / fallback | Cohere + Gemini Free | Combine free tiers |
| Privacy-first / air-gapped | Ollama (local) | No external API calls |

## Gemini

```yaml
embeddings:
  enabled: true
  provider: gemini
  gemini_api_key: ${GEMINI_API_KEY}
  gemini_model: text-embedding-004
  dimensions: 3072
  batch_size: 100
  task_type: RETRIEVAL_DOCUMENT
```

## Cohere

```yaml
embeddings:
  enabled: true
  provider: cohere
  api_key: ${COHERE_API_KEY}
  model: embed-v4.0
  dimensions: 1536
  batch_size: 80
  input_type: search_document
  truncate: END
```

## OpenAI-compatible (OpenAI, Azure, LiteLLM, etc.)

```yaml
embeddings:
  enabled: true
  provider: openai_compat
  endpoint: https://api.openai.com/v1
  model: text-embedding-3-small
  api_key: ${OPENAI_API_KEY}
  dimensions: 1536
  batch_size: 100
```

## Provider fallback

```yaml
embeddings:
  enabled: true
  provider: cohere
  api_key: ${COHERE_API_KEY}
  model: embed-v4.0

  fallback_provider: gemini
  gemini_api_key: ${GEMINI_API_KEY}
  gemini_model: text-embedding-004

  dimensions: 768   # must match across providers
```
