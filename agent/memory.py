"""
Dual-memory manager: mem0 (short-term) + cognee (long-term).

Architecture:
  ┌─────────────────────────────────────────────────────────────────┐
  │ DualMemoryManager                                               │
  │                                                                 │
  │  ┌────────────────────────────┐  ┌──────────────────────────┐ │
  │  │ mem0 (Short-term)          │  │ cognee (Long-term)       │ │
  │  │────────────────────────────│  │──────────────────────────│ │
  │  │ • Recent conversation      │  │ • Knowledge graphs       │ │
  │  │ • Session-scoped facts     │  │ • Domain expertise       │ │
  │  │ • User preferences         │  │ • Safety documents       │ │
  │  │ • Last N turns context     │  │ • Entity relationships   │ │
  │  │                            │  │                          │ │
  │  │ Storage: pgvector          │  │ Storage: pgvector + Neo4j│ │
  │  │ Retention: ephemeral       │  │ Retention: persistent    │ │
  │  └────────────────────────────┘  └──────────────────────────┘ │
  └─────────────────────────────────────────────────────────────────┘

Usage:
  1. Short-term (mem0): Inject recent conversational context into system prompts
     → "User prefers metric units", "Asked about EGLL 10 minutes ago"

  2. Long-term (cognee): Retrieve domain knowledge for complex queries
     → "Runway incursion prevention procedures", "TCAS alert protocols"

Configuration:
  LLM (fact extraction) → MODEL_CHOICE via BASE_URL (e.g. OpenRouter)
  Embedder              → EMBED_BASE_URL, EMBED_API_KEY, EMBED_MODEL
                          (defaults: same as LLM provider, openai/text-embedding-3-small)
  COGNEE_ENABLED        → Set to "false" to disable long-term memory (default: true)
  NEO4J_URI             → Neo4j connection for graph storage (optional, enhances cognee)
  NEO4J_PASSWORD        → Neo4j password (required if using Neo4j)

Environment Variables:
  EMBED_API_KEY       — API key (defaults to LLM_API_KEY)
  EMBED_BASE_URL      — Base URL (defaults to BASE_URL; can be https://api.openai.com/v1)
  EMBED_MODEL         — Model ID (default: openai/text-embedding-3-small)
                        Other options: openai/text-embedding-3-large, cohere/embed-english-v3.0,
                        mistralai/mistral-embed, nomic/nomic-embed-text-v1.5, etc.
                        See: https://openrouter.ai/models?fmt=cards&output_modalities=embeddings
  COGNEE_ENABLED      — Enable/disable long-term memory (default: true)
  NEO4J_URI           — Neo4j URI (default: bolt://localhost:7687)
  NEO4J_PASSWORD      — Neo4j password

Example (.env):
  EMBED_API_KEY=sk-your-key          # override API key
  EMBED_BASE_URL=https://api.openai.com/v1  # use direct OpenAI (not OpenRouter)
  EMBED_MODEL=openai/text-embedding-3-large # use larger (3072 dims) embeddings
  COGNEE_ENABLED=true                # enable long-term knowledge graphs
  NEO4J_PASSWORD=changeme_neo4j      # enable graph DB (optional, enhances cognee)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COMMON_KNOWLEDGE_DATASET = os.getenv("COMMON_KNOWLEDGE_DATASET", "aviation_knowledge")
SESSION_KNOWLEDGE_PREFIX = os.getenv("SESSION_KNOWLEDGE_PREFIX", "session_knowledge")


def _safe_scope_key(raw: str) -> str:
    """Normalize scope keys (session IDs) into dataset-safe identifiers."""
    if not raw:
        return "default"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw.strip())
    return cleaned[:80] or "default"


def _build_mem0_config() -> dict:
    dsn = os.getenv("POSTGRES_DSN", "")
    if not dsn:
        return {}

    # Parse DSN:  postgresql://user:pass@host:port/db
    try:
        # e.g. postgresql://capstone:secret@localhost:5432/capstone
        rest = dsn.replace("postgresql://", "")
        userpass, hostdb = rest.split("@", 1)
        user, password = userpass.split(":", 1)
        hostport, dbname = hostdb.split("/", 1)
        host, *port_part = hostport.split(":")
        port = int(port_part[0]) if port_part else 5432
    except Exception:
        logger.warning("Could not parse POSTGRES_DSN for mem0 config; disabling mem0.")
        return {}

    llm_key   = os.getenv("LLM_API_KEY", "")
    llm_url   = os.getenv("BASE_URL", "https://api.openai.com/v1")
    llm_model = os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini")

    embed_key = os.getenv("EMBED_API_KEY", llm_key)
    embed_url = os.getenv("EMBED_BASE_URL", llm_url)
    embed_model = os.getenv("EMBED_MODEL", "openai/text-embedding-3-small")

    # Determine embedding dimensions based on model
    # (mem0 needs to know vector size for pgvector storage)
    embed_dims_map = {
        "text-embedding-3-small": 1536,          # default
        "openai/text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "openai/text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
        "cohere/embed-english-v3.0": 1024,
        "mistralai/mistral-embed": 1024,
        "nomic/nomic-embed-text-v1.5": 768,
        "nvidia/llama-nemotron-embed-vl-1b-v2": 1152,
    }
    embed_dims = embed_dims_map.get(embed_model, 1536)  # default 1536 if unknown

    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "host": host,
                "port": port,
                "dbname": dbname,
                "user": user,
                "password": password,
                "collection_name": "mem0_memories",
                "embedding_model_dims": embed_dims,  # dynamic based on EMBED_MODEL
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "api_key": llm_key,
                "openai_base_url": llm_url,
                "model": llm_model,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": embed_key,
                "openai_base_url": embed_url,
                "model": embed_model,  # configurable via EMBED_MODEL env var
            },
        },
    }


class MemoryManager:
    """
    Thin async wrapper around mem0 AsyncMemory for SHORT-TERM conversational memory.

    DEPRECATED: Use DualMemoryManager for unified short-term + long-term memory.

    Usage:
        manager = MemoryManager()
        await manager.init()            # call once at startup

        # before each specialist inference:
        ctx = await manager.search(query, user_id=session_id)

        # after each full response (fire-and-forget):
        asyncio.create_task(manager.add(messages, user_id=session_id))
    """

    def __init__(self) -> None:
        self._memory: Any = None

    async def init(self) -> None:
        cfg = _build_mem0_config()
        if not cfg:
            logger.info("mem0 disabled (POSTGRES_DSN not set).")
            return
        try:
            from mem0 import AsyncMemory  # type: ignore
            self._memory = AsyncMemory.from_config(cfg)
            logger.info("mem0 AsyncMemory initialised (pgvector backend).")
        except Exception as e:
            logger.warning("mem0 init failed: %s — long-term memory disabled.", e)
            self._memory = None

    @property
    def available(self) -> bool:
        return self._memory is not None

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> str:
        """Return a formatted string of relevant past memories, or ''."""
        if not self._memory or not query:
            return ""
        try:
            results = await self._memory.asearch(query, user_id=user_id, limit=limit)
            memories = results.get("results", []) if isinstance(results, dict) else results
            if not memories:
                return ""
            lines = [r.get("memory", str(r)) for r in memories[:limit]]
            return "\n".join(f"- {l}" for l in lines)
        except Exception as e:
            logger.debug("mem0 search error: %s", e)
            return ""

    async def add(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Extract and store memories from a completed conversation turn."""
        if not self._memory:
            return
        try:
            kwargs: dict[str, Any] = {"user_id": user_id}
            if metadata:
                kwargs["metadata"] = metadata
            await self._memory.aadd(messages, **kwargs)
        except Exception as e:
            logger.debug("mem0 add error: %s", e)


# ── Dual Memory Manager ───────────────────────────────────────────────────────


class DualMemoryManager:
    """
    Unified memory manager combining mem0 (short-term) + cognee (long-term).

    Best Practices:
    1. **Separation of Concerns**:
       - mem0: Recent conversation, user preferences, session context
       - cognee: Domain knowledge, safety documents, persistent expertise

    2. **When to use each**:
       - Short-term (mem0): "User asked about EGLL weather 5 minutes ago"
       - Long-term (cognee): "FAA regulations for runway incursion prevention"

    3. **Search strategy**:
       - For conversational queries → search_short_term()
       - For domain knowledge queries → search_long_term()
       - For both → search_combined()

    Usage:
        manager = DualMemoryManager()
        await manager.init()

        # Conversational context (short-term)
        ctx = await manager.search_short_term(query, user_id=session_id)

        # Domain knowledge (long-term)
        knowledge = await manager.search_long_term(query)

        # Combined (best practices: separate sections in system prompt)
        combined = await manager.search_combined(query, user_id=session_id)

        # Store conversation (short-term, fire-and-forget)
        asyncio.create_task(manager.add_conversation(messages, user_id=session_id))

        # Ingest document (long-term)
        await manager.add_knowledge(text, metadata={"source": "NTSB"})
    """

    def __init__(self) -> None:
        self._mem0_manager = MemoryManager()
        # Import cognee_client lazily to avoid circular imports
        self._cognee_manager: Any = None

    def get_common_dataset_name(self) -> str:
        """Return the configured shared/common knowledge dataset name."""
        return COMMON_KNOWLEDGE_DATASET

    def get_session_dataset_name(self, session_id: str) -> str:
        """Return a session-scoped long-term knowledge dataset name."""
        return f"{SESSION_KNOWLEDGE_PREFIX}_{_safe_scope_key(session_id)}"

    async def init(self) -> None:
        """Initialize both memory systems."""
        # Initialize short-term (mem0)
        await self._mem0_manager.init()

        # Initialize long-term (cognee)
        try:
            from cognee_client import CogneeManager
            self._cognee_manager = CogneeManager()
            await self._cognee_manager.init()
        except ImportError:
            logger.info("cognee not available; long-term memory disabled.")
            self._cognee_manager = None
        except Exception as e:
            logger.warning("cognee init failed: %s", e)
            self._cognee_manager = None

    @property
    def short_term_available(self) -> bool:
        """Check if short-term memory (mem0) is available."""
        return self._mem0_manager.available

    @property
    def long_term_available(self) -> bool:
        """Check if long-term memory (cognee) is available."""
        return self._cognee_manager is not None and self._cognee_manager.available

    # ── Short-term operations (mem0) ──────────────────────────────────────────

    async def search_short_term(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> str:
        """
        Search short-term conversational memory.

        Returns recent context relevant to the current conversation.
        Example: "User prefers METAR in metric units"

        Args:
            query: Search query
            user_id: Session/user identifier
            limit: Maximum results

        Returns:
            Formatted string of recent memories
        """
        return await self._mem0_manager.search(query, user_id, limit)

    async def add_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Store conversation turn in short-term memory.

        This is fire-and-forget; typically called with asyncio.create_task().

        Args:
            messages: Conversation messages
            user_id: Session/user identifier
            metadata: Optional metadata
        """
        await self._mem0_manager.add(messages, user_id, metadata)

    # ── Long-term operations (cognee) ─────────────────────────────────────────

    async def search_long_term(
        self,
        query: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
        limit: int = 5,
    ) -> str:
        """
        Search long-term knowledge graph.

        Returns domain expertise and persistent knowledge.
        Example: "TCAS resolution advisories require immediate compliance"

        Args:
            query: Search query
            dataset_name: Dataset/collection name
            limit: Maximum results

        Returns:
            Formatted string of knowledge graph results
        """
        if not self._cognee_manager:
            return ""
        return await self._cognee_manager.search(query, dataset_name, limit)

    async def search_session_long_term(
        self,
        query: str,
        session_id: str,
        limit: int = 5,
    ) -> str:
        """Search session-scoped long-term knowledge."""
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.search_long_term(query=query, dataset_name=dataset_name, limit=limit)

    async def search_common_long_term(
        self,
        query: str,
        limit: int = 5,
    ) -> str:
        """Search common/shared long-term knowledge."""
        return await self.search_long_term(
            query=query,
            dataset_name=self.get_common_dataset_name(),
            limit=limit,
        )

    async def add_knowledge(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> bool:
        """
        Ingest document into long-term knowledge graph.

        cognee will extract entities, relationships, and build semantic index.

        Args:
            text: Document content
            metadata: Optional metadata (source, date, type)
            dataset_name: Dataset/collection name

        Returns:
            True if successful
        """
        if not self._cognee_manager:
            return False
        return await self._cognee_manager.add_document(text, metadata, dataset_name)

    async def add_session_knowledge(
        self,
        text: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Ingest knowledge scoped to a single session."""
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.add_knowledge(text=text, metadata=metadata, dataset_name=dataset_name)

    async def add_knowledge_batch(
        self,
        documents: List[Dict[str, Any]],
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> int:
        """
        Ingest multiple documents in batch.

        Args:
            documents: List of {"text": str, "metadata": dict}
            dataset_name: Dataset/collection name

        Returns:
            Number of successfully ingested documents
        """
        if not self._cognee_manager:
            return 0
        return await self._cognee_manager.add_documents_batch(documents, dataset_name)

    async def add_session_knowledge_batch(
        self,
        documents: List[Dict[str, Any]],
        session_id: str,
    ) -> int:
        """Ingest a batch of documents scoped to a single session."""
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.add_knowledge_batch(documents=documents, dataset_name=dataset_name)

    # ── Combined search (best practices) ──────────────────────────────────────

    async def search_combined(
        self,
        query: str,
        user_id: str,
        session_id: str | None = None,
        short_term_limit: int = 3,
        session_long_term_limit: int = 2,
        common_long_term_limit: int = 2,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> str:
        """
        Search BOTH short-term and long-term memory, formatted for LLM context.

        Best Practice: Clearly label each section so the LLM knows the source.

        Args:
            query: Search query
            user_id: Session/user identifier
            short_term_limit: Max short-term results
            session_long_term_limit: Max session-scoped long-term results
            common_long_term_limit: Max shared/common long-term results
            dataset_name: Common long-term dataset name

        Returns:
            Formatted string with both memory types clearly separated
        """
        results = []

        # Short-term context
        short_term = await self.search_short_term(query, user_id, short_term_limit)
        if short_term:
            results.append("## Recent Context (Short-term Memory)")
            results.append(short_term)

        # Session-scoped long-term knowledge
        if session_id:
            session_knowledge = await self.search_session_long_term(
                query=query,
                session_id=session_id,
                limit=session_long_term_limit,
            )
        else:
            session_knowledge = ""

        if session_knowledge:
            if results:
                results.append("")
            results.append("## Session Knowledge (Long-term)")
            results.append(session_knowledge)

        # Common shared long-term knowledge
        common_knowledge = await self.search_long_term(query, dataset_name, common_long_term_limit)
        if common_knowledge:
            if results:
                results.append("")  # blank line separator
            results.append("## Common Knowledge (Long-term)")
            results.append(common_knowledge)

        return "\n".join(results) if results else ""

    # ── Advanced queries (cognee-specific) ────────────────────────────────────

    async def get_entity(
        self,
        entity_name: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve specific entity and relationships from knowledge graph.

        Example: "Show me everything we know about EGLL airport"

        Args:
            entity_name: Entity identifier
            dataset_name: Dataset to search

        Returns:
            Entity data with relationships, or None
        """
        if not self._cognee_manager:
            return None
        return await self._cognee_manager.get_entity(entity_name, dataset_name)

    async def reset_long_term(self, dataset_name: str = COMMON_KNOWLEDGE_DATASET) -> bool:
        """
        Clear long-term knowledge graph (useful for testing/rebuilding).

        WARNING: This is destructive. Only use for development/testing.

        Args:
            dataset_name: Dataset to reset

        Returns:
            True if successful
        """
        if not self._cognee_manager:
            return False
        return await self._cognee_manager.reset_dataset(dataset_name)

