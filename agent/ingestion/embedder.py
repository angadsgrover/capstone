"""
Shared embedding helper for the ingestion pipeline.

Fetches embeddings from OpenRouter's unified embeddings API or direct OpenAI.
Supports all models available on OpenRouter (https://openrouter.ai/models?fmt=cards&output_modalities=embeddings).

Configuration:
  EMBED_API_KEY       — API key (defaults to LLM_API_KEY)
  EMBED_BASE_URL      — Base URL (defaults to BASE_URL, which can be OpenRouter or OpenAI)
  EMBED_MODEL         — Model ID (defaults: openai/text-embedding-3-small)

Model Examples:
  openai/text-embedding-3-small       — 1536 dims, fast, cheap ⭐ recommended
  openai/text-embedding-3-large       — 3072 dims, high quality
  openai/text-embedding-ada-002       — 1536 dims, legacy
  cohere/embed-english-v3.0           — 1024 dims, Cohere model
  nomic/nomic-embed-text-v1.5         — 768 dims, lightweight
  mistralai/mistral-embed             — 1024 dims, Mistral model
  nvidia/llama-nemotron-embed-vl-1b-v2 — multimodal (images + text)

Usage:
  vector = await embed_text("Your text here")   # [1536], cached in embeddings table
  row_id = await embed_and_store(db, "metar", raw_metar_text)  # embed + store
"""
from __future__ import annotations

import logging
import os

import openai

logger = logging.getLogger(__name__)

_client: openai.AsyncOpenAI | None = None


def _get_client() -> openai.AsyncOpenAI:
    """Lazily initialize the OpenAI-compatible client (supports both OpenAI + OpenRouter)."""
    global _client
    if _client is None:
        api_key = os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("EMBED_BASE_URL") or os.getenv("BASE_URL", "https://api.openai.com/v1")

        if not api_key:
            logger.warning("No EMBED_API_KEY or LLM_API_KEY set for embeddings.")

        _client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


def _get_embedding_model() -> str:
    """Get embedding model ID from env, with sensible default."""
    model = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")
    logger.debug("Embedding model: %s", model)
    return model


async def embed_text(text: str) -> list[float]:
    """
    Return an embedding vector for `text` via OpenRouter or OpenAI.

    Truncates input to 8192 chars to stay within model limits.
    Default: text-embedding-3-small returns 1536 dims.

    Raises:
      - openai.APIException if the embedding model is unreachable
      - ValueError if response is malformed
    """
    client = _get_client()
    model = _get_embedding_model()

    try:
        resp = await client.embeddings.create(
            input=text[:8192],  # Truncate to avoid context limits
            model=model,
        )
        if not resp.data or not resp.data[0].embedding:
            raise ValueError("Empty embedding response from API.")
        return resp.data[0].embedding
    except openai.APIError as e:
        logger.error("Embeddings API error (model=%s): %s", model, e)
        raise


async def embed_and_store(
    db,
    source_type: str,
    content: str,
    source_id: int | None = None,
    metadata: dict | None = None,
) -> int:
    """
    Embed `content` and insert into the embeddings table.

    Returns the new row id, or -1 if database is unavailable.

    Args:
      db:          Database instance (should have insert_embedding method)
      source_type: 'metar' | 'taf' | 'safety' | 'conversation'
      content:     Text to embed (truncated to 8192 chars)
      source_id:   Optional FK to metar_history / taf_history / etc.
      metadata:    Optional JSONB metadata (timestamps, icao codes, etc.)
    """
    if not db.available:
        logger.debug("Database unavailable; skipping embedding storage.")
        return -1

    try:
        vector = await embed_text(content)
        row_id = await db.insert_embedding(
            source_type=source_type,
            content=content,
            embedding=vector,
            source_id=source_id,
            metadata=metadata,
        )
        return row_id
    except Exception as e:
        logger.warning("Failed to embed or store (source_type=%s): %s", source_type, e)
        return -1
