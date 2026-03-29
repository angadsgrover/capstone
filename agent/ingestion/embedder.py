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
import hashlib
import httpx
from urllib.parse import urlparse

try:
    from langsmith.run_helpers import get_current_run_tree
except Exception:  # pragma: no cover - optional dependency handling
    def get_current_run_tree():
        return None

logger = logging.getLogger(__name__)

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


def _get_api_key_candidates() -> list[str]:
    candidates: list[str] = []
    for key in [os.getenv("EMBED_API_KEY", ""), os.getenv("LLM_API_KEY", "")]:
        if key and key not in candidates:
            candidates.append(key)
    return candidates


def _get_embedding_model() -> str:
    """Get embedding model ID from env, with sensible default."""
    _, _, model = _get_embed_config()
    logger.debug("Embedding model: %s", model)
    return model


def _get_model_candidates() -> list[str]:
    """Return ordered embedding model candidates; first successful response is used."""
    primary = _get_embedding_model().strip()
    extra_raw = os.getenv("EMBED_MODEL_CANDIDATES", "")
    extra = [m.strip() for m in extra_raw.split(",") if m.strip()]

    defaults = [
        "openai/text-embedding-3-small",
        "text-embedding-3-small",
        "openai/text-embedding-3-large",
        "text-embedding-3-large",
        "openai/text-embedding-ada-002",
        "cohere/embed-english-v3.0",
        "nomic/nomic-embed-text-v1.5",
        "mistralai/mistral-embed",
    ]

    seen: set[str] = set()
    ordered: list[str] = []
    for model in [primary, *extra, *defaults]:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _get_embedding_endpoint() -> str:
    """Resolve embeddings endpoint (override with EMBED_ENDPOINT if needed)."""
    endpoint = os.getenv("EMBED_ENDPOINT", "").strip()
    if endpoint:
        return endpoint.rstrip("/")

    _, base_url, _ = _get_embed_config()

    # Hard default for OpenRouter (requested), with fallback to base URL path.
    if "openrouter.ai" in base_url:
        return "https://openrouter.ai/api/v1/embeddings"

    return base_url.rstrip("/") + "/embeddings"


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


def _local_fallback_embedding(text: str, dims: int = 1536) -> list[float]:
    """Deterministic local fallback embedding when provider calls are unavailable."""
    vals: list[float] = []
    counter = 0
    seed = text.encode("utf-8", errors="ignore")

    while len(vals) < dims:
        digest = hashlib.sha256(seed + str(counter).encode("ascii")).digest()
        counter += 1
        for b in digest:
            # Map byte [0, 255] -> float [-1.0, 1.0]
            vals.append((b / 127.5) - 1.0)
            if len(vals) >= dims:
                break

    return vals


async def embed_text(text: str) -> list[float]:
    """
    Return an embedding vector for `text` via OpenRouter or OpenAI.

    Truncates input to 8192 chars to stay within model limits.
    Default: text-embedding-3-small returns 1536 dims.

    Raises:
      - openai.APIException if the embedding model is unreachable
      - ValueError if response is malformed
    """
    model_candidates = _get_model_candidates()
    endpoint = _get_embedding_endpoint()
    api_keys = _get_api_key_candidates()
    allow_local = os.getenv("EMBED_ALLOW_LOCAL_FALLBACK", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not api_keys:
        if allow_local:
            logger.warning(
                "No embedding API keys configured; using local fallback embedding. "
                "Set EMBED_ALLOW_LOCAL_FALLBACK=false to enforce provider-only mode."
            )
            return _local_fallback_embedding(text)
        raise ValueError("No EMBED_API_KEY or LLM_API_KEY configured for embeddings.")

    errors: list[str] = []

    for idx, api_key in enumerate(api_keys, start=1):
        for midx, model in enumerate(model_candidates, start=1):
            request_body = {
                "input": text[:8192],
                "model": model,
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            # Propagate distributed tracing headers when this call occurs inside
            # an active LangSmith span.
            run_tree = get_current_run_tree()
            if run_tree and hasattr(run_tree, "to_headers"):
                try:
                    headers.update(run_tree.to_headers() or {})
                except Exception:
                    pass

            try:
                async with httpx.AsyncClient(timeout=30) as http_client:
                    r = await http_client.post(endpoint, headers=headers, json=request_body)
                    r.raise_for_status()
                    payload = r.json()
                    vector = _extract_embedding_from_response(payload)
                    if vector:
                        if midx > 1:
                            logger.info("Embedding fallback model in use: %s", model)
                        return vector

                    if isinstance(payload, dict) and payload.get("error"):
                        errors.append(f"key#{idx}/model={model} payload error: {payload.get('error')}")
                    elif isinstance(payload, dict):
                        errors.append(f"key#{idx}/model={model} no data; payload keys={list(payload.keys())}")
                    else:
                        errors.append(f"key#{idx}/model={model} malformed payload type={type(payload).__name__}")
            except httpx.HTTPError as http_error:
                errors.append(f"key#{idx}/model={model} HTTP error: {http_error}")
            except json.JSONDecodeError:
                errors.append(f"key#{idx}/model={model} non-JSON response from {endpoint}")
            except Exception as unknown_error:
                errors.append(f"key#{idx}/model={model} unexpected error: {unknown_error}")

    if allow_local:
        logger.warning(
            "Embedding provider unavailable; using local fallback embedding. "
            "Set EMBED_ALLOW_LOCAL_FALLBACK=false to enforce provider-only mode."
        )
        return _local_fallback_embedding(text)

    raise ValueError("Embedding failed across configured API keys: " + " | ".join(errors))


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
