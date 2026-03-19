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
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from db import Database

logger = logging.getLogger(__name__)

# ── Embedding helper ──────────────────────────────────────────────────────────

async def _embed(text: str) -> list[float]:
    """Generate embedding via OpenAI-compatible API (OpenRouter or direct OpenAI).

    Uses EMBED_MODEL env var (default: openai/text-embedding-3-small, 1536 dims).
    """
    import openai
    client = openai.AsyncOpenAI(
        api_key=os.getenv("EMBED_API_KEY") or os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("EMBED_BASE_URL") or os.getenv("BASE_URL", "https://api.openai.com/v1"),
    )
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


# ── Factory ───────────────────────────────────────────────────────────────────

def make_rag_search_tool(db: "Database") -> StructuredTool:
    """Return a LangChain StructuredTool that performs pgvector RAG search."""

    async def rag_search(query: str, source_type: str = "all", limit: int = 5) -> str:
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
        """
        if not db.available:
            return "RAG search unavailable (database not connected)."
        limit = max(1, min(limit, 20))
        try:
            embedding = await _embed(query)
            rows      = await db.rag_search(embedding, source_type=source_type, limit=limit)
            if not rows:
                return f"No relevant records found for: {query!r}"

            lines = [
                f"[{r['source_type'].upper()} | similarity={r['similarity']:.3f}]\n{r['content']}"
                for r in rows
            ]
            return "\n\n---\n\n".join(lines)
        except Exception as e:
            logger.warning("rag_search error: %s", e)
            return f"RAG search failed: {e}"

    return StructuredTool.from_function(
        coroutine=rag_search,
        name="rag_search",
        description=(
            "Semantic search over historical METAR/TAF data, safety benchmarks, "
            "and past conversation context. Use for historical weather trends and "
            "safety incident lookups."
        ),
        args_schema=RagSearchInput,
    )
