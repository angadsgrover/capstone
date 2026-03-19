"""
Async PostgreSQL connection pool (asyncpg) for the agent service.

Usage in server.py:
    from db import Database
    db = Database()

    @asynccontextmanager
    async def lifespan(app):
        await db.connect()
        yield
        await db.close()

Then pass `db` to any function that needs persistence.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_DSN_ENV = "POSTGRES_DSN"


class Database:
    """Thin wrapper around an asyncpg pool."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        dsn = os.getenv(_DSN_ENV)
        if not dsn:
            logger.warning(
                "%s not set — database features (RAG, conversation persistence) disabled.",
                _DSN_ENV,
            )
            return
        self._pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("PostgreSQL pool opened (%s)", dsn.split("@")[-1])

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("PostgreSQL pool closed.")

    @property
    def available(self) -> bool:
        return self._pool is not None

    # ── helpers ───────────────────────────────────────────────────────────────

    async def save_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a single message to the conversations table."""
        if not self._pool:
            return
        await self._pool.execute(
            """
            INSERT INTO conversations (session_id, role, content, metadata)
            VALUES ($1, $2, $3, $4)
            """,
            session_id,
            role,
            content,
            metadata,
        )

    async def rag_search(
        self,
        query_embedding: list[float],
        source_type: str = "all",
        limit: int = 5,
    ) -> list[asyncpg.Record]:
        """
        Cosine similarity search over the embeddings table.

        Returns up to `limit` records sorted by descending similarity.
        Each record has: content, metadata, source_type, similarity.
        """
        if not self._pool:
            return []
        return await self._pool.fetch(
            """
            SELECT content, metadata, source_type,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM   embeddings
            WHERE  ($2 = 'all' OR source_type = $2)
            ORDER  BY embedding <=> $1::vector
            LIMIT  $3
            """,
            query_embedding,
            source_type,
            limit,
        )

    async def insert_embedding(
        self,
        source_type: str,
        content: str,
        embedding: list[float],
        source_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Insert a pre-computed embedding; returns the new row id."""
        if not self._pool:
            return -1
        row = await self._pool.fetchrow(
            """
            INSERT INTO embeddings (source_type, source_id, content, embedding, metadata)
            VALUES ($1, $2, $3, $4::vector, $5)
            RETURNING id
            """,
            source_type,
            source_id,
            content,
            embedding,
            metadata,
        )
        return row["id"]
