"""
Unified memory manager built on Mem0 Cloud.

Architecture:
  - Short-term memory: recent conversational context scoped by session/user
  - Long-term memory: persistent knowledge store scoped by dataset/app_id

Both memory tiers use Mem0 Cloud via MemoryClient.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COMMON_KNOWLEDGE_DATASET = os.getenv("COMMON_KNOWLEDGE_DATASET", "aviation_knowledge")
SESSION_KNOWLEDGE_PREFIX = os.getenv("SESSION_KNOWLEDGE_PREFIX", "session_knowledge")
MEM0_SHORT_TERM_APP_ID = os.getenv("MEM0_SHORT_TERM_APP_ID", "chat_sessions")
MEM0_LONG_TERM_USER_ID = os.getenv("MEM0_LONG_TERM_USER_ID", "aviation_knowledge_base")


def _safe_scope_key(raw: str) -> str:
    """Normalize scope keys (session IDs) into dataset-safe identifiers."""
    if not raw:
        return "default"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw.strip())
    return cleaned[:80] or "default"


def _extract_result_items(results: Any) -> list[dict[str, Any]]:
    """Normalize Mem0 search response shapes into a list of dict items."""
    if isinstance(results, dict):
        for key in ("results", "data", "memories"):
            value = results.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [results]

    if isinstance(results, list):
        normalized: list[dict[str, Any]] = []
        for item in results:
            if isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"memory": str(item)})
        return normalized

    if results is None:
        return []

    return [{"memory": str(results)}]


def _memory_text(item: dict[str, Any]) -> str:
    """Extract a displayable memory text from a Mem0 result item."""
    return str(
        item.get("memory")
        or item.get("text")
        or item.get("content")
        or item.get("value")
        or ""
    ).strip()


class _Mem0BaseClient:
    """Shared Mem0 Cloud client helper with resilient method invocation."""

    def __init__(self) -> None:
        self._client: Any = None

    async def _call_add(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: str,
        app_id: str,
        metadata: dict[str, Any],
    ) -> None:
        if not self._client:
            return

        try:
            await asyncio.to_thread(
                self._client.add,
                messages,
                user_id=user_id,
                app_id=app_id,
                metadata=metadata,
                async_mode=False,
            )
            return
        except TypeError:
            pass

        try:
            await asyncio.to_thread(
                self._client.add,
                messages,
                user_id=user_id,
                app_id=app_id,
                metadata=metadata,
            )
            return
        except TypeError:
            pass

        try:
            await asyncio.to_thread(
                self._client.add,
                messages,
                user_id=user_id,
                metadata=metadata,
            )
        except TypeError:
            await asyncio.to_thread(self._client.add, messages, user_id=user_id)

    async def _call_search(
        self,
        query: str,
        *,
        user_id: str,
        app_id: str,
        limit: int,
    ) -> Any:
        if not self._client:
            return []

        # Mem0 Cloud v2 search expects explicit filters; older releases used
        # direct user_id/app_id kwargs. Try newest contract first, then fall back.
        filter_and = {
            "AND": [
                {"user_id": user_id},
                {"app_id": app_id},
            ]
        }

        attempts = [
            {"filters": filter_and, "top_k": limit},
            {"filters": filter_and, "limit": limit},
            {"user_id": user_id, "app_id": app_id, "top_k": limit},
            {"user_id": user_id, "app_id": app_id, "limit": limit},
            {"user_id": user_id, "top_k": limit},
            {"user_id": user_id, "limit": limit},
            {"user_id": user_id},
        ]

        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                return await asyncio.to_thread(
                    self._client.search,
                    query,
                    **kwargs,
                )
            except TypeError:
                continue
            except Exception as e:
                last_error = e
                continue

        if last_error is not None:
            raise last_error

        return []

    async def _call_delete_all(self, *, user_id: str, app_id: str) -> bool:
        if not self._client:
            return False

        try:
            await asyncio.to_thread(self._client.delete_all, user_id=user_id, app_id=app_id)
            return True
        except TypeError:
            pass

        try:
            filters = {"AND": [{"user_id": user_id}, {"app_id": app_id}]}
            await asyncio.to_thread(self._client.delete_all, filters=filters)
            return True
        except Exception:
            return False


class MemoryManager(_Mem0BaseClient):
    """Async wrapper around Mem0 Cloud for short-term conversational memory."""

    def __init__(self) -> None:
        super().__init__()

    async def init(self) -> None:
        api_key = os.getenv("MEM0_API_KEY") or os.getenv("MEM0_KEY")
        if not api_key:
            logger.info("Mem0 short-term memory disabled: MEM0_API_KEY not set.")
            return

        try:
            from mem0 import MemoryClient  # type: ignore

            self._client = MemoryClient(api_key=api_key)
            logger.info("Mem0 Cloud short-term memory initialized.")
        except Exception as e:
            logger.warning("Mem0 short-term init failed: %s", e)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> str:
        if not self._client or not query:
            return ""

        try:
            raw = await self._call_search(
                query,
                user_id=user_id,
                app_id=MEM0_SHORT_TERM_APP_ID,
                limit=max(1, min(limit, 20)),
            )
            items = _extract_result_items(raw)
            if not items:
                return ""

            lines: list[str] = []
            for item in items[:limit]:
                text = _memory_text(item)
                if text:
                    lines.append(f"- {text}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("Mem0 short-term search error: %s", e)
            return ""

    async def add(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._client or not messages:
            return

        try:
            mem0_metadata = {
                "memory_scope": "short_term",
                **(metadata or {}),
            }
            await self._call_add(
                messages,
                user_id=user_id,
                app_id=MEM0_SHORT_TERM_APP_ID,
                metadata=mem0_metadata,
            )
        except Exception as e:
            logger.debug("Mem0 short-term add error: %s", e)


class Mem0LongTermManager(_Mem0BaseClient):
    """Long-term domain knowledge manager backed by Mem0 Cloud."""

    def __init__(self) -> None:
        super().__init__()
        self._enabled = os.getenv("MEM0_LONG_TERM_ENABLED", "true").lower() == "true"

    async def init(self) -> None:
        if not self._enabled:
            logger.info("Mem0 long-term memory disabled (MEM0_LONG_TERM_ENABLED=false).")
            return

        api_key = os.getenv("MEM0_API_KEY") or os.getenv("MEM0_KEY")
        if not api_key:
            logger.info("Mem0 long-term memory disabled: MEM0_API_KEY not set.")
            self._enabled = False
            return

        try:
            from mem0 import MemoryClient  # type: ignore

            self._client = MemoryClient(api_key=api_key)
            logger.info("Mem0 Cloud long-term memory initialized.")
        except Exception as e:
            logger.warning("Mem0 long-term init failed: %s", e)
            self._enabled = False
            self._client = None

    @property
    def available(self) -> bool:
        return self._enabled and self._client is not None

    async def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> bool:
        if not self.available or not text:
            return False

        try:
            messages = [{"role": "user", "content": text}]
            mem0_metadata = {
                "memory_scope": "long_term",
                "dataset": dataset_name,
                **(metadata or {}),
            }
            await self._call_add(
                messages,
                user_id=MEM0_LONG_TERM_USER_ID,
                app_id=dataset_name,
                metadata=mem0_metadata,
            )
            return True
        except Exception as e:
            logger.debug("Mem0 long-term add_document error: %s", e)
            return False

    async def add_documents_batch(
        self,
        documents: List[Dict[str, Any]],
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> int:
        if not self.available:
            return 0

        success_count = 0
        for doc in documents:
            text = str(doc.get("text", "") or "")
            metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
            if await self.add_document(text=text, metadata=metadata, dataset_name=dataset_name):
                success_count += 1

        return success_count

    async def search(
        self,
        query: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
        limit: int = 5,
    ) -> str:
        if not self.available or not query:
            return ""

        try:
            raw = await self._call_search(
                query,
                user_id=MEM0_LONG_TERM_USER_ID,
                app_id=dataset_name,
                limit=max(1, min(limit, 20)),
            )
            items = _extract_result_items(raw)
            if not items:
                return ""

            lines: list[str] = []
            for idx, item in enumerate(items[:limit], start=1):
                text = _memory_text(item)
                if not text:
                    continue
                score = item.get("score")
                if isinstance(score, (float, int)):
                    lines.append(f"{idx}. {text} (relevance: {float(score):.2f})")
                else:
                    lines.append(f"{idx}. {text}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("Mem0 long-term search error: %s", e)
            return ""

    async def get_entity(
        self,
        entity_name: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> Optional[Dict[str, Any]]:
        if not self.available or not entity_name:
            return None

        try:
            raw = await self._call_search(
                entity_name,
                user_id=MEM0_LONG_TERM_USER_ID,
                app_id=dataset_name,
                limit=10,
            )
            items = _extract_result_items(raw)
            matches = []
            for item in items:
                text = _memory_text(item)
                if text:
                    matches.append(
                        {
                            "id": item.get("id"),
                            "memory": text,
                            "score": item.get("score"),
                            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                        }
                    )

            if not matches:
                return None

            return {
                "name": entity_name,
                "dataset": dataset_name,
                "matches": matches,
            }
        except Exception as e:
            logger.debug("Mem0 long-term get_entity error: %s", e)
            return None

    async def reset_dataset(self, dataset_name: str = COMMON_KNOWLEDGE_DATASET) -> bool:
        if not self.available:
            return False
        return await self._call_delete_all(user_id=MEM0_LONG_TERM_USER_ID, app_id=dataset_name)


class DualMemoryManager:
    """Unified manager combining Mem0 short-term and long-term memory."""

    def __init__(self) -> None:
        self._mem0_manager = MemoryManager()
        self._long_term_manager = Mem0LongTermManager()

    def get_common_dataset_name(self) -> str:
        return COMMON_KNOWLEDGE_DATASET

    def get_session_dataset_name(self, session_id: str) -> str:
        return f"{SESSION_KNOWLEDGE_PREFIX}_{_safe_scope_key(session_id)}"

    async def init(self) -> None:
        await self._mem0_manager.init()
        await self._long_term_manager.init()

    @property
    def short_term_available(self) -> bool:
        return self._mem0_manager.available

    @property
    def long_term_available(self) -> bool:
        return self._long_term_manager.available

    async def search_short_term(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> str:
        return await self._mem0_manager.search(query, user_id, limit)

    async def add_conversation(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._mem0_manager.add(messages, user_id, metadata)

    async def search_long_term(
        self,
        query: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
        limit: int = 5,
    ) -> str:
        if not self._long_term_manager:
            return ""
        return await self._long_term_manager.search(query, dataset_name, limit)

    async def search_session_long_term(
        self,
        query: str,
        session_id: str,
        limit: int = 5,
    ) -> str:
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.search_long_term(query=query, dataset_name=dataset_name, limit=limit)

    async def search_common_long_term(
        self,
        query: str,
        limit: int = 5,
    ) -> str:
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
        if not self._long_term_manager:
            return False
        return await self._long_term_manager.add_document(text, metadata, dataset_name)

    async def add_session_knowledge(
        self,
        text: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.add_knowledge(text=text, metadata=metadata, dataset_name=dataset_name)

    async def add_knowledge_batch(
        self,
        documents: List[Dict[str, Any]],
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> int:
        if not self._long_term_manager:
            return 0
        return await self._long_term_manager.add_documents_batch(documents, dataset_name)

    async def add_session_knowledge_batch(
        self,
        documents: List[Dict[str, Any]],
        session_id: str,
    ) -> int:
        dataset_name = self.get_session_dataset_name(session_id)
        return await self.add_knowledge_batch(documents=documents, dataset_name=dataset_name)

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
        results = []

        short_term = await self.search_short_term(query, user_id, short_term_limit)
        if short_term:
            results.append("## Recent Context (Short-term Memory)")
            results.append(short_term)

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

        common_knowledge = await self.search_long_term(query, dataset_name, common_long_term_limit)
        if common_knowledge:
            if results:
                results.append("")
            results.append("## Common Knowledge (Long-term)")
            results.append(common_knowledge)

        return "\n".join(results) if results else ""

    async def get_entity(
        self,
        entity_name: str,
        dataset_name: str = COMMON_KNOWLEDGE_DATASET,
    ) -> Optional[Dict[str, Any]]:
        if not self._long_term_manager:
            return None
        return await self._long_term_manager.get_entity(entity_name, dataset_name)

    async def reset_long_term(self, dataset_name: str = COMMON_KNOWLEDGE_DATASET) -> bool:
        if not self._long_term_manager:
            return False
        return await self._long_term_manager.reset_dataset(dataset_name)
