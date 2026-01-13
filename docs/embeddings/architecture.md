<!-- Refactored embeddings docs generated 2026-01-13 -->

# Architecture

## Why these design choices?

| Design | Choice | Why |
|--------|--------|-----|
| Provider | Gemini (default) | Strong quality/cost ratio, 3072 dims, generous free tier |
| Dimensions | 3072 | Captures nuance in business email and jargon |
| Normalization | L2-normalize vectors | Enables faster inner product search |
| Index | HNSW with `vector_ip_ops` / `halfvec_ip_ops` | Inner product is efficient for normalized vectors |
| Vector type | `halfvec` for dims > 2000 | Allows HNSW indexing up to ~4000 dims |
| Search | Metadata-augmented | Hard filters prevent “vector drift” |

## Metadata-augmented search

The strongest pattern is **hard filters first**, then semantic scoring.

- Hard filters (metadata): sender, date, folder, has_attachments, unread, etc.
- Semantic ranker: inner product / cosine-equivalent on normalized vectors
