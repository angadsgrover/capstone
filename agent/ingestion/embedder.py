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
import json
import httpx
from urllib.parse import urlparse

import openai

logger = logging.getLogger(__name__)

_client: openai.AsyncOpenAI | None = None


def _normalize_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1"

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url

    # Common shorthand in .env: https://openrouter.ai
    if "openrouter.ai" in host:
        if path in ("", "/", "/api", "/api/", "/api/v", "/api/v/"):
            return origin.rstrip("/") + "/api/v1"
        if not path.startswith("/api/"):
            return url + "/api/v1"

    # Common shorthand in .env: https://api.openai.com
    if "api.openai.com" in host and path in ("", "/"):
        return url + "/v1"

    return url


def _get_embed_config() -> tuple[str, str, str]:
    api_key = os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY", "")
    base_url = _normalize_base_url(os.getenv("EMBED_BASE_URL") or os.getenv("BASE_URL", "https://api.openai.com/v1"))
    model = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")
    return api_key, base_url, model


def _get_client() -> openai.AsyncOpenAI:
    """Lazily initialize the OpenAI-compatible client (supports both OpenAI + OpenRouter)."""
    global _client
    if _client is None:
        api_key, base_url, _ = _get_embed_config()

        if not api_key:
            logger.warning("No EMBED_API_KEY or LLM_API_KEY set for embeddings.")

        _client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


def _get_embedding_model() -> str:
    """Get embedding model ID from env, with sensible default."""
    _, _, model = _get_embed_config()
    logger.debug("Embedding model: %s", model)
    return model


def _extract_embedding_from_response(resp: object) -> list[float] | None:
    # Typical OpenAI Python SDK shape (Pydantic object)
    if hasattr(resp, "data") and getattr(resp, "data"):
        first = resp.data[0]  # type: ignore[attr-defined]
        if hasattr(first, "embedding") and first.embedding:  # type: ignore[attr-defined]
            return first.embedding  # type: ignore[return-value]

    # Some compatible gateways may return dict-like payloads.
    if isinstance(resp, dict):
        data = resp.get("data") or []
        if data and isinstance(data[0], dict) and data[0].get("embedding"):
            return data[0]["embedding"]

    # Defensive fallback if a proxy/client returned a JSON string.
    if isinstance(resp, str):
        try:
            payload = json.loads(resp)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            data = payload.get("data") or []
            if data and isinstance(data[0], dict) and data[0].get("embedding"):
                return data[0]["embedding"]

    return None


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
    api_key, base_url, _ = _get_embed_config()

    request_body = {
        "input": text[:8192],
        "model": model,
    }

    try:
        resp = await client.embeddings.create(**request_body)
        vector = _extract_embedding_from_response(resp)
        if vector:
            return vector

        raise ValueError(f"Malformed embedding response type={type(resp).__name__}")
    except openai.APIError as e:
        logger.error("Embeddings API error (model=%s): %s", model, e)
        raise
    except Exception as sdk_error:
        logger.warning("SDK embeddings call failed; falling back to raw HTTP (model=%s): %s", model, sdk_error)

        if not api_key:
            raise

        endpoint = base_url.rstrip("/") + "/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as http_client:
            r = await http_client.post(endpoint, headers=headers, json=request_body)
            r.raise_for_status()
            payload = r.json()
            vector = _extract_embedding_from_response(payload)
            if vector:
                return vector

            if isinstance(payload, dict) and payload.get("error"):
                raise ValueError(f"Embedding API error payload: {payload.get('error')}")

            if isinstance(payload, dict):
                raise ValueError(f"No embedding data received. Payload keys: {list(payload.keys())}")

        raise ValueError("Malformed embedding response after raw HTTP fallback.")


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
