"""
cognee knowledge graph search tool — structured knowledge retrieval from long-term memory.

This tool provides access to cognee's knowledge graph, which contains:
- Safety documents (incident reports, regulations, manuals)
- Domain expertise (aviation concepts, procedures, protocols)
- Entity relationships (airports, aircraft, organizations)
- Temporal knowledge (how information evolves over time)

The tool is created via a factory so it closes over the shared DualMemoryManager instance.

Usage in _build_graph:
    from tools.cognee_search import make_cognee_search_tool
    cognee_tool = make_cognee_search_tool(memory_manager)
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


@traceable(name="retriever.cognee_search", run_type="retriever")
async def _trace_cognee_retrieval(query: str, dataset: str, documents: list[dict]) -> list[dict]:
    return documents


# ── Input schema ──────────────────────────────────────────────────────────────

class CogneeSearchInput(BaseModel):
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
        description="Maximum number of results to return (1–10).",
    )


# ── Factory ───────────────────────────────────────────────────────────────────

def make_cognee_search_tool(memory_manager: "DualMemoryManager") -> StructuredTool:
    """Return a LangChain StructuredTool that performs cognee knowledge graph search."""

    async def cognee_search(
        query: str,
        dataset: str = "aviation_knowledge",
        limit: int = 5
    ) -> str:
        """
        Search the long-term knowledge graph for domain expertise.

        This tool retrieves structured knowledge from cognee, which builds
        semantic knowledge graphs from ingested documents. Use this for:

        - **Safety Procedures**: "What are the steps for TCAS resolution?"
        - **Regulations**: "FAA requirements for runway incursion reporting"
        - **Domain Concepts**: "Explain the difference between METAR and TAF"
        - **Incident Analysis**: "Common causes of landing gear failures"
        - **Entity Information**: "What do we know about EGLL airport?"

        Args:
            query: Natural-language query for domain knowledge.
            dataset: Dataset to search (default: aviation_knowledge).
            limit: Maximum results (1–10).

        Returns:
            Formatted knowledge graph results with entities and relationships.

        Example Queries:
            - "What are standard runway incursion prevention procedures?"
            - "Explain TCAS resolution advisory protocols"
            - "What weather phenomena cause the most flight delays?"
            - "Show me incidents involving Boeing 737 in 2024"
        """
        if not memory_manager.long_term_available:
            return (
                "Long-term knowledge graph unavailable. "
                "cognee is not initialized or disabled (set COGNEE_ENABLED=true)."
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
                await _trace_cognee_retrieval(query=query, dataset=dataset, documents=retriever_docs)

            return (
                f"## Knowledge Graph Results\n"
                f"Query: {query!r}\n"
                f"Dataset: {dataset}\n\n"
                f"{results}"
            )

        except Exception as e:
            logger.warning("cognee_search error: %s", e)
            return f"Knowledge graph search failed: {e}"

    return StructuredTool.from_function(
        coroutine=cognee_search,
        name="knowledge_graph_search",
        description=(
            "Search long-term knowledge graph for domain expertise, safety procedures, "
            "regulations, and entity information. Use for questions requiring deep "
            "domain knowledge beyond current weather/flight data."
        ),
        args_schema=CogneeSearchInput,
    )


# ── Entity retrieval tool (advanced) ──────────────────────────────────────────

class CogneeEntityInput(BaseModel):
    entity_name: str = Field(
        description=(
            "Entity identifier to retrieve (e.g., 'EGLL', 'Boeing 737', 'TCAS'). "
            "Returns all known facts and relationships for this entity."
        )
    )
    dataset: str = Field(
        default="aviation_knowledge",
        description="Dataset to search (default: aviation_knowledge).",
    )


def make_cognee_entity_tool(memory_manager: "DualMemoryManager") -> StructuredTool:
    """Return a LangChain StructuredTool for entity-specific queries."""

    async def cognee_get_entity(
        entity_name: str,
        dataset: str = "aviation_knowledge",
    ) -> str:
        """
        Retrieve all known facts and relationships for a specific entity.

        Use this for targeted entity queries like:
        - "What do we know about EGLL airport?"
        - "Show me all incidents involving Boeing 737"
        - "Tell me about TCAS systems"

        Args:
            entity_name: Entity identifier (ICAO code, aircraft type, system name, etc.)
            dataset: Dataset to search (default: aviation_knowledge).

        Returns:
            Entity information with relationships and facts.
        """
        if not memory_manager.long_term_available:
            return "Long-term knowledge graph unavailable."

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

            # Format entity data
            lines = [f"## Entity: {entity_name}"]
            if isinstance(entity, dict):
                for key, value in entity.items():
                    if key != "name":
                        lines.append(f"**{key.title()}**: {value}")
            else:
                lines.append(str(entity))

            return "\n".join(lines)

        except Exception as e:
            logger.warning("cognee_get_entity error: %s", e)
            return f"Entity retrieval failed: {e}"

    return StructuredTool.from_function(
        coroutine=cognee_get_entity,
        name="get_entity_info",
        description=(
            "Retrieve detailed information about a specific entity (airport, aircraft, "
            "system, etc.) from the knowledge graph. Use for targeted fact lookups."
        ),
        args_schema=CogneeEntityInput,
    )
