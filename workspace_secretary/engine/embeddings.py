"""
Embeddings client for OpenAI-compatible API endpoints.

This module handles embedding generation for semantic search capabilities.
It supports any OpenAI-compatible embeddings endpoint (OpenAI, Azure OpenAI,
local models via Ollama/vLLM, etc.).
"""

import asyncio
import hashlib
import logging
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
    ):
        """Initialize embeddings client.

        Args:
            endpoint: Base URL for embeddings API (e.g., "https://api.openai.com/v1")
            model: Model name (e.g., "text-embedding-3-small")
            api_key: API key for authentication (optional for local models)
            dimensions: Expected embedding dimensions
            batch_size: Maximum texts per batch request
            timeout: Request timeout in seconds
        """
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.timeout = timeout

        # Ensure endpoint ends with /embeddings for OpenAI-compatible APIs
        if not self.endpoint.endswith("/embeddings"):
            self.embeddings_url = f"{self.endpoint}/embeddings"
        else:
            self.embeddings_url = self.endpoint

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _compute_hash(self, text: str) -> str:
        """Compute content hash for deduplication."""
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def _prepare_text(self, subject: Optional[str], body: str) -> str:
        """Prepare email text for embedding.

        Combines subject and body, normalizes whitespace, and truncates
        to reasonable length for embedding models.
        """
        # Combine subject and body
        parts = []
        if subject:
            parts.append(f"Subject: {subject}")
        if body:
            # Clean up body - normalize whitespace
            clean_body = " ".join(body.split())
            parts.append(clean_body)

        text = "\n".join(parts)

        # Truncate to ~8000 tokens (roughly 32000 chars for English)
        # Most embedding models have 8192 token limit
        max_chars = 32000
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
        content_hashes = [self._compute_hash(t) for t in texts]

        payload = {
            "model": self.model,
            "input": texts,
        }

        if self.dimensions and self.dimensions != 1536:
            payload["dimensions"] = self.dimensions

        logger.debug(
            f"Requesting embeddings for {len(texts)} texts from {self.embeddings_url}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.embeddings_url,
                headers=self._get_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        logger.debug(
            f"Received embeddings response with {len(data.get('data', []))} vectors"
        )

        # Parse response
        results = []
        embeddings_data = data.get("data", [])
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        tokens_per_text = total_tokens // len(texts) if texts else 0

        # Sort by index to maintain order
        embeddings_data.sort(key=lambda x: x.get("index", 0))

        for i, embedding_item in enumerate(embeddings_data):
            embedding = embedding_item.get("embedding", [])
            results.append(
                EmbeddingResult(
                    text=texts[i],
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

        total_stored = 0
        while True:
            emails = self.database.get_emails_needing_embedding(
                folder, limit=self.batch_size
            )

            if not emails:
                if total_stored > 0:
                    logger.info(f"Embedded {total_stored} emails from {folder}")
                else:
                    logger.debug(f"No emails need embedding in {folder}")
                return total_stored

            logger.debug(f"Embedding batch of {len(emails)} emails from {folder}")

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
                try:
                    self.database.upsert_embedding(
                        email_uid=email["uid"],
                        email_folder=email["folder"],
                        embedding=result.embedding,
                        model=result.model,
                        content_hash=result.content_hash,
                    )
                    total_stored += 1
                except Exception as e:
                    logger.error(
                        f"Failed to store embedding for UID {email['uid']}: {e}"
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


def create_embeddings_client(config: Any) -> Optional[EmbeddingsClient]:
    """Create embeddings client from config if enabled.

    Args:
        config: EmbeddingsConfig from server configuration

    Returns:
        EmbeddingsClient if enabled, None otherwise
    """
    if not config.enabled:
        return None

    if not config.endpoint:
        logger.warning("Embeddings enabled but no endpoint configured")
        return None

    return EmbeddingsClient(
        endpoint=config.endpoint,
        model=config.model,
        api_key=config.api_key,
        dimensions=config.dimensions,
        batch_size=config.batch_size,
    )
