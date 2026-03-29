"""
Apache AGE graph search tool — runs openCypher queries against the aviation
knowledge graph stored in PostgreSQL via the Apache AGE extension.

Requires PostgreSQL with AGE installed (see infra/Dockerfile.postgres).
Falls back gracefully if AGE is absent.

Factory usage:
    from tools.graph_search import make_graph_search_tool
    graph_tool = make_graph_search_tool(db)
"""
from __future__ import annotations

import json
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
    from db import Database

logger = logging.getLogger(__name__)

GRAPH_NAME = "aviation"


@traceable(name="retriever.graph_search", run_type="retriever")
async def _trace_graph_retrieval(cypher: str, documents: list[dict]) -> list[dict]:
    return documents


class GraphSearchInput(BaseModel):
    cypher: str = Field(
        description=(
            "An openCypher MATCH query to run against the 'aviation' graph. "
            "Return variables are automatically included. "
            "Example: MATCH (a:Airport {icao: 'VHHH'})-[:ROUTE]->(b:Airport) RETURN b.icao, b.name"
        )
    )
    limit: int = Field(default=10, description="Maximum rows to return (1–50).")


def make_graph_search_tool(db: "Database") -> StructuredTool:
    """Return a LangChain StructuredTool for Apache AGE Cypher queries."""

    async def graph_search(cypher: str, limit: int = 10) -> str:
        """
        Run an openCypher query against the aviation knowledge graph.

        The graph contains:
          - Airport nodes  (:Airport {icao, name, lat, lon})
          - Route edges    (:ROUTE {distance_nm, operator})
          - Safety events  (:SafetyEvent {severity, date, event_type})

        Use for:
         - Finding airports connected by routes
         - Identifying airports with recent safety incidents
         - Traversing aviation ontology relationships

        Args:
            cypher: openCypher MATCH … RETURN query (no LIMIT needed).
            limit:  Max rows (default 10).
        """
        if not db.available:
            return "Graph search unavailable (database not connected)."
        limit = max(1, min(limit, 50))
        try:
            # Wrap in AGE cypher() call; result columns must be declared as agtype
            sql = f"""
                SELECT row_to_json(t) AS result
                FROM (
                    SELECT * FROM cypher('{GRAPH_NAME}', $$ {cypher} LIMIT {limit} $$)
                    AS (data agtype)
                ) t
            """
            rows = await db._pool.fetch(sql)  # type: ignore[union-attr]
            if not rows:
                return "No results."
            results = [json.loads(r["result"]) for r in rows]

            documents = [
                {
                    "page_content": json.dumps(result, default=str),
                    "type": "Document",
                    "metadata": {
                        "graph": GRAPH_NAME,
                        "cypher": cypher,
                        "row_index": idx,
                    },
                }
                for idx, result in enumerate(results, start=1)
            ]
            await _trace_graph_retrieval(cypher=cypher, documents=documents)

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            # AGE not installed or graph not initialised — return graceful message
            if "age" in str(e).lower() or "cypher" in str(e).lower():
                return (
                    "Graph search unavailable: Apache AGE is not installed on this "
                    "PostgreSQL instance. Use rag_search for semantic queries instead."
                )
            logger.warning("graph_search error: %s", e)
            return f"Graph query failed: {e}"

    return StructuredTool.from_function(
        coroutine=graph_search,
        name="graph_search",
        description=(
            "Run openCypher queries against the aviation knowledge graph (Apache AGE). "
            "Use for airport relationships, route lookups, and safety event traversal."
        ),
        args_schema=GraphSearchInput,
    )
