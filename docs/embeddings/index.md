<!-- Refactored embeddings docs generated 2026-01-13 -->

# MailPilot Semantic Search & Embeddings

Google MailPilot relies on PostgreSQL + pgvector for meaning-based search. The embedding layer feeds tools like `semantic_search_emails`, `semantic_search_filtered`, and `find_related_emails`, so MCP clients can query by **concepts** ("budget concerns") instead of literal keywords. Postgres is mandatory in v5.0.0; SQLite is no longer supported for embeddings.

## Read next

- [Overview](./overview.md)
- [Architecture](./architecture.md)
- [Dimensions & storage](./dimensions.md)
- [Migration](./migration.md)
- [Providers](./providers.md)
- [Quick start](./quick-start.md)
- [Configuration reference](./config-reference.md)
- [Database schema](./database-schema.md)
- [Performance tuning](./performance.md)
- [MCP tools](./mcp-tools.md)
- [Web UI integration](./web-ui.md)
- [Troubleshooting](./troubleshooting.md)
- [Cost estimation](./cost.md)
