"""
cognee long-term knowledge graph manager.

cognee builds structured knowledge graphs from unstructured documents,
enabling semantic search over entities, relationships, and domain concepts.

Use cases:
  - Ingest safety documents (incident reports, regulations, manuals)
  - Build knowledge graphs of aviation domain concepts
  - Graph-based RAG: retrieve entities + relationships
  - Temporal reasoning: track how knowledge evolves

Architecture:
  Short-term memory (mem0)     → Recent conversational context (last N turns)
  Long-term memory (cognee)    → Persistent knowledge graph (domain expertise)

Configuration:
  COGNEE_API_KEY       — Optional API key if using cognee cloud
  POSTGRES_DSN         — Database for vector storage (shared with mem0)
  NEO4J_URI            — Neo4j connection (default: bolt://localhost:7687)
  NEO4J_USER           — Neo4j username (default: neo4j)
  NEO4J_PASSWORD       — Neo4j password (required if Neo4j enabled)
  COGNEE_ENABLED       — Set to "false" to disable (default: true if deps available)

Example (.env):
  POSTGRES_DSN=postgresql://capstone:secret@localhost:5432/capstone
  NEO4J_URI=bolt://localhost:7687
  NEO4J_USER=neo4j
  NEO4J_PASSWORD=changeme_neo4j
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _should_enable_cognee() -> bool:
    """Check if cognee should be enabled based on environment."""
    if os.getenv("COGNEE_ENABLED", "true").lower() == "false":
        return False
    dsn = os.getenv("POSTGRES_DSN", "")
    if not dsn:
        logger.info("cognee disabled: POSTGRES_DSN not set.")
        return False
    return True


def _build_cognee_config() -> Dict[str, Any]:
    """Build cognee configuration from environment variables."""
    dsn = os.getenv("POSTGRES_DSN", "")
    if not dsn:
        return {}

    # Parse PostgreSQL DSN
    try:
        rest = dsn.replace("postgresql://", "")
        userpass, hostdb = rest.split("@", 1)
        user, password = userpass.split(":", 1)
        hostport, dbname = hostdb.split("/", 1)
        host, *port_part = hostport.split(":")
        port = int(port_part[0]) if port_part else 5432
    except Exception:
        logger.warning("Could not parse POSTGRES_DSN for cognee; disabling.")
        return {}

    config = {
        "vector_store": {
            "provider": "postgres",
            "config": {
                "host": host,
                "port": port,
                "dbname": dbname,
                "user": user,
                "password": password,
            },
        },
    }

    # Optional: Neo4j graph database (enhances relationship queries)
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "")

    if neo4j_password:
        config["graph_store"] = {
            "provider": "neo4j",
            "config": {
                "uri": neo4j_uri,
                "user": neo4j_user,
                "password": neo4j_password,
            },
        }

    # LLM for knowledge extraction (reuse main LLM config)
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
    llm_model = os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini")

    config["llm"] = {
        "provider": "openai",
        "config": {
            "api_key": llm_key,
            "openai_base_url": llm_url,
            "model": llm_model,
        },
    }

    # Embedder (reuse embeddings config)
    embed_key = os.getenv("EMBED_API_KEY", llm_key)
    embed_url = os.getenv("EMBED_BASE_URL", llm_url)
    embed_model = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")

    config["embedder"] = {
        "provider": "openai",
        "config": {
            "api_key": embed_key,
            "openai_base_url": embed_url,
            "model": embed_model,
        },
    }

    return config


class CogneeManager:
    """
    Async wrapper around cognee for long-term knowledge graph management.

    Usage:
        manager = CogneeManager()
        await manager.init()

        # Ingest document
        await manager.add_document(
            text="NTSB report: ...",
            metadata={"source": "NTSB", "date": "2024-01-15"}
        )

        # Search knowledge graph
        results = await manager.search("What are common causes of runway incursions?")
    """

    def __init__(self) -> None:
        self._cognee: Any = None
        self._enabled = _should_enable_cognee()

    async def init(self) -> None:
        """Initialize cognee with configured backend."""
        if not self._enabled:
            logger.info("cognee disabled (COGNEE_ENABLED=false or missing POSTGRES_DSN).")
            return

        try:
            import cognee

            config = _build_cognee_config()
            if not config:
                logger.warning("cognee config empty; disabling.")
                self._enabled = False
                return

            # Initialize cognee with configuration
            await cognee.config.set_config(config)
            self._cognee = cognee

            logger.info(
                "cognee initialized (vector_store=%s, graph_store=%s).",
                config.get("vector_store", {}).get("provider", "none"),
                config.get("graph_store", {}).get("provider", "none"),
            )
        except ImportError:
            logger.warning("cognee package not installed; long-term memory disabled.")
            self._enabled = False
        except Exception as e:
            logger.warning("cognee init failed: %s — long-term memory disabled.", e)
            self._enabled = False

    @property
    def available(self) -> bool:
        """Check if cognee is available."""
        return self._enabled and self._cognee is not None

    async def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        dataset_name: str = "aviation_knowledge",
    ) -> bool:
        """
        Ingest a document into the knowledge graph.

        cognee will:
        1. Extract entities (airports, aircraft, people, organizations)
        2. Identify relationships (caused_by, located_at, operated_by)
        3. Build semantic embeddings for retrieval
        4. Store in vector DB + optional graph DB

        Args:
            text: Document content
            metadata: Optional metadata (source, date, type)
            dataset_name: Dataset/collection name

        Returns:
            True if successful, False otherwise
        """
        if not self.available or not text:
            return False

        try:
            # Add document to dataset
            await self._cognee.add(text, dataset_name=dataset_name, metadata=metadata or {})

            # Process/cognify to extract knowledge
            await self._cognee.cognify(dataset_name=dataset_name)

            logger.debug("cognee ingested document (dataset=%s, len=%d)", dataset_name, len(text))
            return True
        except Exception as e:
            logger.debug("cognee add_document error: %s", e)
            return False

    async def add_documents_batch(
        self,
        documents: List[Dict[str, Any]],
        dataset_name: str = "aviation_knowledge",
    ) -> int:
        """
        Ingest multiple documents in batch.

        Args:
            documents: List of {"text": str, "metadata": dict}
            dataset_name: Dataset/collection name

        Returns:
            Number of successfully ingested documents
        """
        if not self.available:
            return 0

        success_count = 0
        for doc in documents:
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})
            if await self.add_document(text, metadata, dataset_name):
                success_count += 1

        return success_count

    async def search(
        self,
        query: str,
        dataset_name: str = "aviation_knowledge",
        limit: int = 5,
    ) -> str:
        """
        Search knowledge graph for relevant entities and relationships.

        Returns formatted string of results (for LLM context injection).

        Args:
            query: Search query
            dataset_name: Dataset to search
            limit: Maximum results

        Returns:
            Formatted string of knowledge graph results
        """
        if not self.available or not query:
            return ""

        try:
            # Search knowledge graph
            results = await self._cognee.search(
                query,
                dataset_name=dataset_name,
                limit=limit,
            )

            if not results:
                return ""

            # Format results for LLM consumption
            lines = []
            for i, result in enumerate(results[:limit], 1):
                # cognee returns structured knowledge (entities + relationships)
                if isinstance(result, dict):
                    text = result.get("text", result.get("content", str(result)))
                    score = result.get("score", 0.0)
                    lines.append(f"{i}. {text} (relevance: {score:.2f})")
                else:
                    lines.append(f"{i}. {result}")

            return "\n".join(lines)
        except Exception as e:
            logger.debug("cognee search error: %s", e)
            return ""

    async def get_entity(
        self,
        entity_name: str,
        dataset_name: str = "aviation_knowledge",
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific entity and its relationships from knowledge graph.

        Useful for:
        - "What do we know about EGLL airport?"
        - "Show me incidents involving Boeing 737"

        Args:
            entity_name: Entity identifier (e.g., "EGLL", "Boeing 737")
            dataset_name: Dataset to search

        Returns:
            Entity data with relationships, or None
        """
        if not self.available:
            return None

        try:
            # cognee's graph query API
            entity = await self._cognee.get_entity(
                entity_name,
                dataset_name=dataset_name,
            )
            return entity
        except AttributeError:
            # Fallback: search for entity
            results = await self.search(entity_name, dataset_name, limit=1)
            if results:
                return {"name": entity_name, "info": results}
            return None
        except Exception as e:
            logger.debug("cognee get_entity error: %s", e)
            return None

    async def reset_dataset(self, dataset_name: str = "aviation_knowledge") -> bool:
        """
        Clear a dataset (useful for testing or rebuilding knowledge).

        Args:
            dataset_name: Dataset to reset

        Returns:
            True if successful
        """
        if not self.available:
            return False

        try:
            await self._cognee.prune()  # Clear all data
            logger.info("cognee dataset reset: %s", dataset_name)
            return True
        except Exception as e:
            logger.debug("cognee reset error: %s", e)
            return False
