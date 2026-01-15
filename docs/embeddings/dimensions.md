<!-- Refactored embeddings docs generated 2026-01-13 -->

# Dimensions & storage

::: danger Important
**Embedding dimensions cannot be changed after initial sync without re-embedding all emails.**
See [Migration](./migration.md).
:::

## Automatic quantization for high dimensions

pgvector’s HNSW index has practical limits around ~2000 dims for 32-bit vectors (8KB block size).
For dimensions > 2000, Google MailPilot can store embeddings as `halfvec` (16-bit quantization).

| Dimensions | Vector type | Index ops | Notes |
|------------|-------------|-----------|-------|
| ≤ 2000 | `vector` (32-bit) | `vector_ip_ops` | Standard precision |
| > 2000 | `halfvec` (16-bit) | `halfvec_ip_ops` | Quantized, small recall tradeoff |

## Dimension selection guide

| Dimensions | Storage (25k emails) | Best for |
|------------|-----------------------|----------|
| 768 | ~60 MB | Storage-constrained or simple queries |
| 1536 | ~120 MB | Balanced / general purpose |
| 3072 | ~240 MB | Best nuance for business email |

### When to use each

**768**
- Personal mail, simple queries
- Faster index builds
- Storage constrained

**1536**
- General purpose balance
- Mixed personal + work mail

**3072** (recommended)
- Business email, nuanced search
- More future-proof
- Higher storage
