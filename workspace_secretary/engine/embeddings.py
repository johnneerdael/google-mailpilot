"""
Embeddings client for OpenAI-compatible API endpoints.

This module handles embedding generation for semantic search capabilities.
It supports any OpenAI-compatible embeddings endpoint (OpenAI, Azure OpenAI,
local models via Ollama/vLLM, etc.).
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    text: str
    embedding: list[float]
    model: str
    content_hash: str
    tokens_used: int


class EmbeddingsClient:
    """Client for generating embeddings via OpenAI-compatible API."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: Optional[str] = None,
        dimensions: int = 1536,
        batch_size: int = 100,
        timeout: float = 30.0,
        max_concurrent: int = 4,
        max_chars: int = 500000,
    ):
        """Initialize embeddings client.

        Args:
            endpoint: Base URL for embeddings API (e.g., "https://api.openai.com/v1")
            model: Model name (e.g., "text-embedding-3-small")
            api_key: API key for authentication (optional for local models)
            dimensions: Expected embedding dimensions
            batch_size: Maximum texts per batch request
            timeout: Request timeout in seconds
            max_concurrent: Maximum concurrent embedding requests
            max_chars: Maximum characters per text (for truncation)
        """
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.max_chars = max_chars

        if not self.endpoint.endswith("/embeddings"):
            self.embeddings_url = f"{self.endpoint}/embeddings"
        else:
            self.embeddings_url = self.endpoint

        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _compute_hash(self, text: str) -> str:
        """Compute content hash for deduplication."""
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def _prepare_text(self, subject: Optional[str], body: str) -> str:
        """Prepare email text for embedding.

        Combines subject and body, normalizes whitespace, and truncates
        to reasonable length for embedding models.
        """
        parts = []
        if subject:
            parts.append(f"Subject: {subject}")
        if body:
            clean_body = " ".join(body.split())
            parts.append(clean_body)

        text = "\n".join(parts)

        max_chars = self.max_chars
        if len(text) > max_chars:
            text = text[:max_chars]

        return text

    async def embed_text(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            EmbeddingResult with embedding vector

        Raises:
            httpx.HTTPError: On API request failure
        """
        results = await self.embed_texts([text])
        return results[0]

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts.

        Handles batching automatically if texts exceed batch_size.

        Args:
            texts: List of texts to embed

        Returns:
            List of EmbeddingResult objects in same order as input
        """
        if not texts:
            return []

        results: list[EmbeddingResult] = []

        # Process in batches
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_results = await self._embed_batch(batch)
            results.extend(batch_results)

        return results

    async def _embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        def is_valid_text(t: str) -> bool:
            if not t or not t.strip():
                return False
            stripped = t.strip()
            if len(stripped) < 3:
                return False
            if not any(c.isalnum() for c in stripped):
                return False
            return True

        filtered_texts = [t.strip() for t in texts if is_valid_text(t)]
        if not filtered_texts:
            return [
                EmbeddingResult(
                    text=t if t else "",
                    embedding=[],
                    model=self.model,
                    content_hash="",
                    tokens_used=0,
                )
                for t in texts
            ]

        content_hashes = [self._compute_hash(t) for t in filtered_texts]

        payload = {
            "model": self.model,
            "input": filtered_texts,
        }

        if self.dimensions and self.dimensions != 1536:
            payload["dimensions"] = self.dimensions

        logger.debug(
            f"Requesting embeddings for {len(filtered_texts)} texts from {self.embeddings_url}"
        )

        try:
            async with self._get_semaphore():
                client = await self._get_client()
                response = await client.post(
                    self.embeddings_url,
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Embeddings API error {e.response.status_code}: {e.response.text[:500]}"
            )
            raise

        logger.debug(
            f"Received embeddings response with {len(data.get('data', []))} vectors"
        )

        # Parse response - map back to filtered_texts
        results = []
        embeddings_data = data.get("data", [])
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        tokens_per_text = total_tokens // len(filtered_texts) if filtered_texts else 0

        # Sort by index to maintain order
        embeddings_data.sort(key=lambda x: x.get("index", 0))

        for i, embedding_item in enumerate(embeddings_data):
            embedding = embedding_item.get("embedding", [])
            results.append(
                EmbeddingResult(
                    text=filtered_texts[i],
                    embedding=embedding,
                    model=self.model,
                    content_hash=content_hashes[i],
                    tokens_used=tokens_per_text,
                )
            )

        return results

    async def embed_email(self, subject: Optional[str], body: str) -> EmbeddingResult:
        """Generate embedding for an email.

        Args:
            subject: Email subject
            body: Email body text

        Returns:
            EmbeddingResult with embedding vector
        """
        text = self._prepare_text(subject, body)
        return await self.embed_text(text)

    async def embed_emails(self, emails: list[dict[str, Any]]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple emails.

        Args:
            emails: List of email dicts with 'subject' and 'body_text' keys

        Returns:
            List of EmbeddingResult objects
        """
        texts = [
            self._prepare_text(e.get("subject"), e.get("body_text", "")) for e in emails
        ]
        return await self.embed_texts(texts)

    async def embed_query(self, query: str) -> EmbeddingResult:
        """Embed a search query. For OpenAI-compatible APIs, same as embed_text."""
        return await self.embed_text(query)


class EmbeddingsSyncWorker:
    """Background worker for syncing embeddings to database."""

    def __init__(
        self,
        client: EmbeddingsClient,
        database: Any,  # DatabaseInterface
        folders: list[str],
        batch_size: int = 50,
    ):
        """Initialize sync worker.

        Args:
            client: Embeddings client for generating vectors
            database: Database interface with embedding support
            folders: List of folders to sync embeddings for
            batch_size: Emails to process per sync cycle
        """
        self.client = client
        self.database = database
        self.folders = folders
        self.batch_size = batch_size
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def sync_folder(self, folder: str) -> int:
        if not self.database.supports_embeddings():
            logger.warning("Database does not support embeddings")
            return 0

        total_needing = self.database.count_emails_needing_embedding(folder)
        total_stored = 0
        total_failed = 0

        if total_needing == 0:
            logger.debug(f"No emails need embedding in {folder}")
            return 0

        logger.info(f"[{folder}] Starting embeddings for {total_needing} emails")

        while True:
            emails = self.database.get_emails_needing_embedding(
                folder, limit=self.batch_size
            )

            if not emails:
                logger.info(
                    f"[{folder}] Embeddings complete: {total_stored} succeeded, {total_failed} failed"
                )
                return total_stored

            try:
                results = await self.client.embed_emails(emails)
            except httpx.TimeoutException:
                logger.error(f"Embeddings timeout for {len(emails)} emails in {folder}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"Embeddings API error {e.response.status_code}: {e.response.text[:200]}"
                )
                raise

            for email, result in zip(emails, results):
                if not result.embedding:
                    total_failed += 1
                    continue
                try:
                    self.database.upsert_embedding(
                        email_uid=email["uid"],
                        email_folder=email["folder"],
                        embedding=result.embedding,
                        model=result.model,
                        content_hash=email["content_hash"],
                    )
                    total_stored += 1
                except Exception as e:
                    total_failed += 1
                    logger.error(
                        f"Failed to store embedding for UID {email['uid']}: {e}"
                    )

            current_remaining = self.database.count_emails_needing_embedding(folder)
            done = total_needing - current_remaining
            if done % 200 == 0 or current_remaining == 0:
                logger.info(
                    f"[{folder}] {done}/{total_needing} embeddings done ({total_stored} stored, {total_failed} skipped)"
                )

    async def sync_all_folders(self) -> int:
        """Sync embeddings for all configured folders.

        Returns:
            Total number of emails embedded
        """
        total = 0
        for folder in self.folders:
            try:
                count = await self.sync_folder(folder)
                total += count
            except Exception as e:
                logger.error(f"Error syncing embeddings for {folder}: {e}")
        return total

    async def start_background_sync(self, interval_seconds: float = 60.0) -> None:
        """Start background sync task.

        Args:
            interval_seconds: Time between sync cycles
        """
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._background_loop(interval_seconds))
        logger.info("Embeddings background sync started")

    async def stop_background_sync(self) -> None:
        """Stop background sync task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Embeddings background sync stopped")

    async def _background_loop(self, interval: float) -> None:
        """Background sync loop."""
        while self._running:
            try:
                await self.sync_all_folders()
            except Exception as e:
                logger.error(f"Error in embeddings sync loop: {e}")

            await asyncio.sleep(interval)


class CohereEmbeddingsClient:
    """Native Cohere embeddings client with input_type support and rate limiting."""

    TOKENS_PER_MINUTE = 100_000
    CHARS_PER_TOKEN = 4

    def __init__(
        self,
        api_key: str,
        model: str = "embed-v4.0",
        dimensions: int = 1536,
        batch_size: int = 96,
        input_type: str = "search_document",
        truncate: str = "END",
        max_chars: int = 500000,
    ):
        try:
            import cohere
        except ImportError:
            raise ImportError("cohere package required: pip install cohere")

        self.client = cohere.ClientV2(api_key=api_key)
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.input_type = input_type
        self.truncate = truncate
        self.max_chars = max_chars
        self._closed = False
        self._tokens_used_this_minute = 0
        self._minute_start = time.monotonic()
        self._rate_limit_lock = asyncio.Lock()

    def _estimate_tokens(self, texts: list[str]) -> int:
        return sum(len(t) // self.CHARS_PER_TOKEN + 1 for t in texts)

    async def _wait_for_rate_limit(self, estimated_tokens: int) -> None:
        async with self._rate_limit_lock:
            now = time.monotonic()
            elapsed = now - self._minute_start
            if elapsed >= 60:
                self._tokens_used_this_minute = 0
                self._minute_start = now
                elapsed = 0

            if self._tokens_used_this_minute > 0 and (
                self._tokens_used_this_minute + estimated_tokens
                > self.TOKENS_PER_MINUTE
            ):
                wait_time = 60 - elapsed + 1
                logger.info(
                    f"Rate limit approaching ({self._tokens_used_this_minute:,} tokens used), waiting {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)
                self._tokens_used_this_minute = 0
                self._minute_start = time.monotonic()

            self._tokens_used_this_minute += estimated_tokens

    async def close(self) -> None:
        self._closed = True

    def _compute_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def _prepare_text(self, subject: Optional[str], body: str) -> str:
        parts = []
        if subject:
            parts.append(f"Subject: {subject}")
        if body:
            clean_body = " ".join(body.split())
            parts.append(clean_body)
        text = "\n".join(parts)
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
        return text

    async def embed_text(self, text: str) -> EmbeddingResult:
        results = await self.embed_texts([text])
        return results[0]

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []

        results: list[EmbeddingResult] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_results = await self._embed_batch(batch)
            results.extend(batch_results)
        return results

    async def _embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        def is_valid_text(t: str) -> bool:
            if not t or not t.strip():
                return False
            stripped = t.strip()
            return len(stripped) >= 3 and any(c.isalnum() for c in stripped)

        filtered_texts = [t.strip() for t in texts if is_valid_text(t)]
        if not filtered_texts:
            return [
                EmbeddingResult(
                    text=t if t else "",
                    embedding=[],
                    model=self.model,
                    content_hash="",
                    tokens_used=0,
                )
                for t in texts
            ]

        content_hashes = [self._compute_hash(t) for t in filtered_texts]
        estimated_tokens = self._estimate_tokens(filtered_texts)
        await self._wait_for_rate_limit(estimated_tokens)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.embed(
                    texts=filtered_texts,
                    model=self.model,
                    input_type=self.input_type,
                    embedding_types=["float"],
                    truncate=self.truncate,
                )
                break
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    wait_time = (2**attempt) * 15
                    logger.warning(
                        f"Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    self._tokens_used_this_minute = 0
                    self._minute_start = time.monotonic()
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Cohere embeddings API error after {max_retries} retries: {e}"
                        )
                        raise
                else:
                    logger.error(f"Cohere embeddings API error: {e}")
                    raise

        embeddings = response.embeddings.float_ or []
        results = []
        for i, embedding in enumerate(embeddings):
            results.append(
                EmbeddingResult(
                    text=filtered_texts[i],
                    embedding=list(embedding),
                    model=self.model,
                    content_hash=content_hashes[i],
                    tokens_used=0,
                )
            )
        return results

    async def embed_email(self, subject: Optional[str], body: str) -> EmbeddingResult:
        text = self._prepare_text(subject, body)
        return await self.embed_text(text)

    async def embed_emails(self, emails: list[dict[str, Any]]) -> list[EmbeddingResult]:
        texts = [
            self._prepare_text(e.get("subject"), e.get("body_text", "")) for e in emails
        ]
        return await self.embed_texts(texts)

    async def embed_query(self, query: str) -> EmbeddingResult:
        """Embed a search query using search_query input type for better retrieval."""
        original_input_type = self.input_type
        self.input_type = "search_query"
        try:
            return await self.embed_text(query)
        finally:
            self.input_type = original_input_type


def create_embeddings_client(
    config: Any,
) -> Optional[EmbeddingsClient | CohereEmbeddingsClient]:
    if not config.enabled:
        return None

    provider = getattr(config, "provider", "openai_compat")

    if provider == "cohere":
        if not config.api_key:
            logger.warning("Cohere embeddings enabled but no api_key configured")
            return None
        return CohereEmbeddingsClient(
            api_key=config.api_key,
            model=config.model,
            dimensions=config.dimensions,
            batch_size=config.batch_size,
            input_type=getattr(config, "input_type", "search_document"),
            truncate=getattr(config, "truncate", "END"),
            max_chars=getattr(config, "max_chars", 500000),
        )

    # Default: OpenAI-compatible
    if not config.endpoint:
        logger.warning("Embeddings enabled but no endpoint configured")
        return None

    return EmbeddingsClient(
        endpoint=config.endpoint,
        model=config.model,
        api_key=config.api_key,
        dimensions=config.dimensions,
        batch_size=config.batch_size,
        max_chars=getattr(config, "max_chars", 500000),
    )
