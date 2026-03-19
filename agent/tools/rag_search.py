"""
RAG search tool — semantic search over historical METAR/TAF data and safety
benchmarks stored in the pgvector `embeddings` table.

The tool is created via a factory so it closes over the shared Database and
embed function instances.

Usage in _build_graph:
    from tools.rag_search import make_rag_search_tool
    rag_tool = make_rag_search_tool(db)
"""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except Exception:
    BM25_AVAILABLE = False

if TYPE_CHECKING:
    from db import Database

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EMBED_CLIENT = None


def _get_embed_client():
    """Lazily create and reuse the embedding client for lower request overhead."""
    global _EMBED_CLIENT
    if _EMBED_CLIENT is None:
        import openai

        _EMBED_CLIENT = openai.AsyncOpenAI(
            api_key=os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("EMBED_BASE_URL") or os.getenv("BASE_URL", "https://api.openai.com/v1"),
        )
    return _EMBED_CLIENT


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenizer tuned for ICAO/IATA and technical tokens."""
    return _TOKEN_RE.findall((text or "").lower())


def _normalize_scores(values: list[float]) -> list[float]:
    """Min-max normalize score vectors to [0, 1] with stable fallback."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [1.0 for _ in values]
    span = hi - lo
    return [(v - lo) / span for v in values]

# ── Embedding helper ──────────────────────────────────────────────────────────

async def _embed(text: str) -> list[float]:
    """Generate embedding via OpenAI-compatible API (OpenRouter or direct OpenAI).

    Uses EMBED_MODEL env var (default: openai/text-embedding-3-small, 1536 dims).
    """
    client = _get_embed_client()
    model = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")
    resp = await client.embeddings.create(
        input=text,
        model=model,
    )
    return resp.data[0].embedding


# ── Input schema ──────────────────────────────────────────────────────────────

class RagSearchInput(BaseModel):
    query: str = Field(description="Natural-language query to search for.")
    source_type: str = Field(
        default="all",
        description=(
            "Filter by data type: 'metar', 'taf', 'safety', 'conversation', "
            "or 'all' to search across everything."
        ),
    )
    limit: int = Field(default=5, description="Maximum number of results to return (1–20).")
    hybrid: bool = Field(
        default=True,
        description="Enable hybrid reranking (vector similarity + BM25 lexical score).",
    )


# ── Factory ───────────────────────────────────────────────────────────────────

def make_rag_search_tool(db: "Database") -> StructuredTool:
    """Return a LangChain StructuredTool that performs pgvector RAG search."""

    async def rag_search(
        query: str,
        source_type: str = "all",
        limit: int = 5,
        hybrid: bool = True,
    ) -> str:
        """
        Semantic search over historical METAR/TAF data, safety benchmarks,
        and past conversation context stored in PostgreSQL + pgvector.

        Use this to:
         - Find similar past weather conditions at an airport
         - Retrieve relevant safety incidents or bulletins
         - Surface historical context for a query

        Args:
            query:       Natural-language search query.
            source_type: 'metar' | 'taf' | 'safety' | 'conversation' | 'all'
            limit:       Max results (default 5).
            hybrid:      Enable BM25+vector reranking.
        """
        if not db.available:
            return "RAG search unavailable (database not connected)."
        limit = max(1, min(limit, 20))
        try:
            embedding = await _embed(query)
            # Over-fetch for hybrid ranking while keeping strict upper bound for latency.
            overfetch_factor = int(os.getenv("RAG_HYBRID_OVERFETCH_FACTOR", "4"))
            overfetch_cap = int(os.getenv("RAG_HYBRID_OVERFETCH_CAP", "60"))
            overfetch = min(max(limit * max(overfetch_factor, 1), limit), max(overfetch_cap, limit))

            rows = await db.rag_search(embedding, source_type=source_type, limit=overfetch)
            if not rows:
                return f"No relevant records found for: {query!r}"

            selected_rows = rows
            if hybrid and BM25_AVAILABLE and len(rows) > 1:
                vector_scores = [float(r.get("similarity", 0.0)) for r in rows]
                vector_norm = _normalize_scores(vector_scores)

                corpus_tokens = [_tokenize(str(r.get("content", ""))) for r in rows]
                query_tokens = _tokenize(query)
                bm25 = BM25Okapi(corpus_tokens)
                bm25_scores = bm25.get_scores(query_tokens).tolist()
                bm25_norm = _normalize_scores([float(x) for x in bm25_scores])

                vector_weight = float(os.getenv("RAG_HYBRID_VECTOR_WEIGHT", "0.7"))
                bm25_weight = float(os.getenv("RAG_HYBRID_BM25_WEIGHT", "0.3"))
                total = vector_weight + bm25_weight
                if total <= 0:
                    vector_weight, bm25_weight = 0.7, 0.3
                    total = 1.0
                vector_weight /= total
                bm25_weight /= total

                combined_rows = []
                for i, row in enumerate(rows):
                    hybrid_score = (vector_weight * vector_norm[i]) + (bm25_weight * bm25_norm[i])
                    row_dict = dict(row)
                    row_dict["hybrid_score"] = hybrid_score
                    row_dict["bm25_score"] = bm25_scores[i]
                    combined_rows.append(row_dict)

                combined_rows.sort(key=lambda r: r.get("hybrid_score", 0.0), reverse=True)
                selected_rows = combined_rows[:limit]
            else:
                selected_rows = list(rows)[:limit]

            lines = [
                (
                    f"[{r['source_type'].upper()} | similarity={float(r.get('similarity', 0.0)):.3f}"
                    + (
                        f" | hybrid={float(r.get('hybrid_score', 0.0)):.3f}"
                        if r.get("hybrid_score") is not None
                        else ""
                    )
                    + "]\n"
                    + str(r.get("content", ""))
                )
                for r in selected_rows
            ]
            return "\n\n---\n\n".join(lines)
        except Exception as e:
            logger.warning("rag_search error: %s", e)
            return f"RAG search failed: {e}"

    return StructuredTool.from_function(
        coroutine=rag_search,
        name="rag_search",
        description=(
            "Hybrid semantic + lexical search over historical METAR/TAF data, "
            "safety benchmarks, and past conversation context. Uses vector search "
            "with optional BM25 reranking for better exact-match retrieval "
            "(e.g., ICAO codes and flight IDs)."
        ),
        args_schema=RagSearchInput,
    )
