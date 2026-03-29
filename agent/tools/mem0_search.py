"""
Mem0 long-term search tools for domain knowledge retrieval.

The tools are created via factories so they can close over the shared
DualMemoryManager instance.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

try:
    from langsmith import traceable
except Exception:  # pragma: no cover - safe no-op fallback when langsmith unavailable
    def traceable(*args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _decorator(fn):
            return fn

        return _decorator

if TYPE_CHECKING:
    from memory import DualMemoryManager

logger = logging.getLogger(__name__)


def _coerce_documents(results: object, limit: int, dataset: str) -> list[dict]:
    documents: list[dict] = []

    if isinstance(results, list):
        for idx, item in enumerate(results[:limit], start=1):
            if isinstance(item, dict):
                page_content = str(item.get("page_content") or item.get("content") or item)
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                metadata = {"dataset": dataset, "rank": idx, **metadata}
            else:
                page_content = str(item)
                metadata = {"dataset": dataset, "rank": idx}

            documents.append(
                {
                    "page_content": page_content,
                    "type": "Document",
                    "metadata": metadata,
                }
            )
        return documents

    if isinstance(results, dict):
        return [
            {
                "page_content": str(results.get("page_content") or results.get("content") or results),
                "type": "Document",
                "metadata": {"dataset": dataset, **(results.get("metadata") or {})},
            }
        ]

    text = str(results or "")
    if not text:
        return []

    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    if not chunks:
        chunks = [text]

    return [
        {
            "page_content": chunk,
            "type": "Document",
            "metadata": {"dataset": dataset, "rank": idx},
        }
        for idx, chunk in enumerate(chunks[:limit], start=1)
    ]


@traceable(name="retriever.mem0_search", run_type="retriever")
async def _trace_mem0_retrieval(query: str, dataset: str, documents: list[dict]) -> list[dict]:
    return documents


class Mem0SearchInput(BaseModel):
    query: str = Field(
        description=(
            "Natural-language query for domain knowledge. "
            "Examples: 'TCAS alert procedures', 'runway incursion prevention', "
            "'What are the causes of windshear incidents?'"
        )
    )
    dataset: str = Field(
        default="aviation_knowledge",
        description="Dataset to search (default: aviation_knowledge).",
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results to return (1-10).",
    )


def make_mem0_search_tool(memory_manager: "DualMemoryManager") -> StructuredTool:
    """Return a StructuredTool that performs long-term Mem0 knowledge search."""

    async def mem0_search(
        query: str,
        dataset: str = "aviation_knowledge",
        limit: int = 5,
    ) -> str:
        if not memory_manager.long_term_available:
            return (
                "Long-term memory unavailable. "
                "Mem0 Cloud is not initialized or disabled (set MEM0_API_KEY)."
            )

        limit = max(1, min(limit, 10))

        try:
            results = await memory_manager.search_long_term(
                query=query,
                dataset_name=dataset,
                limit=limit,
            )

            if not results:
                return (
                    f"No knowledge found for query: {query!r}\n\n"
                    "Try:\n"
                    "- Rephrasing your query\n"
                    "- Using broader terms (e.g., 'weather incidents' vs 'windshear')\n"
                    "- Checking if relevant documents have been ingested"
                )

            retriever_docs = _coerce_documents(results=results, limit=limit, dataset=dataset)
            if retriever_docs:
                await _trace_mem0_retrieval(query=query, dataset=dataset, documents=retriever_docs)

            return (
                f"## Long-term Memory Results\n"
                f"Query: {query!r}\n"
                f"Dataset: {dataset}\n\n"
                f"{results}"
            )

        except Exception as e:
            logger.warning("mem0_search error: %s", e)
            return f"Long-term memory search failed: {e}"

    return StructuredTool.from_function(
        coroutine=mem0_search,
        name="knowledge_graph_search",
        description=(
            "Search long-term memory for domain expertise, safety procedures, "
            "regulations, and entity information. Use for questions requiring deep "
            "domain knowledge beyond current weather/flight data."
        ),
        args_schema=Mem0SearchInput,
    )


class Mem0EntityInput(BaseModel):
    entity_name: str = Field(
        description=(
            "Entity identifier to retrieve (e.g., 'EGLL', 'Boeing 737', 'TCAS'). "
            "Returns known facts related to this entity."
        )
    )
    dataset: str = Field(
        default="aviation_knowledge",
        description="Dataset to search (default: aviation_knowledge).",
    )


def make_mem0_entity_tool(memory_manager: "DualMemoryManager") -> StructuredTool:
    """Return a StructuredTool for entity-focused Mem0 lookups."""

    async def mem0_get_entity(
        entity_name: str,
        dataset: str = "aviation_knowledge",
    ) -> str:
        if not memory_manager.long_term_available:
            return "Long-term memory unavailable."

        try:
            entity = await memory_manager.get_entity(
                entity_name=entity_name,
                dataset_name=dataset,
            )

            if not entity:
                return (
                    f"Entity not found: {entity_name!r}\n"
                    "Try using knowledge_graph_search for broader queries."
                )

            lines = [f"## Entity: {entity_name}"]
            if isinstance(entity, dict):
                for key, value in entity.items():
                    if key != "name":
                        lines.append(f"**{key.title()}**: {value}")
            else:
                lines.append(str(entity))

            return "\n".join(lines)

        except Exception as e:
            logger.warning("mem0_get_entity error: %s", e)
            return f"Entity retrieval failed: {e}"

    return StructuredTool.from_function(
        coroutine=mem0_get_entity,
        name="get_entity_info",
        description=(
            "Retrieve detailed information about a specific entity (airport, aircraft, "
            "system, etc.) from long-term memory. Use for targeted fact lookups."
        ),
        args_schema=Mem0EntityInput,
    )
