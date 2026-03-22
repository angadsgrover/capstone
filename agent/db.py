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
import json
from typing import Any

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    asyncpg = None

logger = logging.getLogger(__name__)

_DSN_ENV = "POSTGRES_DSN"


class Database:
    """Thin wrapper around an asyncpg pool."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        if asyncpg is None:
            logger.warning(
                "asyncpg not installed — database features (RAG, conversation persistence) disabled."
            )
            return

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
        # asyncpg does not bind Python lists directly to pgvector; pass literal text.
        embedding_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
        metadata_json = json.dumps(metadata) if metadata is not None else None
        row = await self._pool.fetchrow(
            """
            INSERT INTO embeddings (source_type, source_id, content, embedding, metadata)
            VALUES ($1, $2, $3, $4::vector, $5)
            RETURNING id
            """,
            source_type,
            source_id,
            content,
            embedding_literal,
            metadata_json,
        )
        return row["id"]

    async def latest_metar_by_airport(self, limit: int = 12) -> list[asyncpg.Record]:
        """Return latest METAR record per airport."""
        if not self._pool:
            return []
        limit = max(1, min(limit, 50))
        return await self._pool.fetch(
            """
            SELECT x.icao, x.obs_time, x.flight_cat, x.temp_c, x.wind_speed_kt, x.visibility_sm
            FROM (
                SELECT DISTINCT ON (icao)
                    icao, obs_time, flight_cat, temp_c, wind_speed_kt, visibility_sm
                FROM metar_history
                ORDER BY icao, obs_time DESC
            ) x
            ORDER BY x.obs_time DESC
            LIMIT $1
            """,
            limit,
        )

    async def metar_trends(
        self,
        icaos: list[str],
        hours: int = 72,
        per_airport_limit: int = 120,
    ) -> list[asyncpg.Record]:
        """Return time-series METAR points for selected airports."""
        if not self._pool or not icaos:
            return []
        hours = max(1, min(hours, 24 * 14))
        per_airport_limit = max(10, min(per_airport_limit, 500))
        return await self._pool.fetch(
            """
            WITH ranked AS (
                SELECT
                    icao,
                    obs_time,
                    wind_speed_kt,
                    temp_c,
                    ROW_NUMBER() OVER (PARTITION BY icao ORDER BY obs_time DESC) AS rn
                FROM metar_history
                WHERE icao = ANY($1::text[])
                  AND obs_time >= NOW() - ($2::text || ' hours')::interval
            )
            SELECT icao, obs_time, wind_speed_kt, temp_c
            FROM ranked
            WHERE rn <= $3
            ORDER BY icao, obs_time ASC
            """,
            icaos,
            str(hours),
            per_airport_limit,
        )

    async def safety_heatmap(self, limit: int = 20) -> list[asyncpg.Record]:
        """Aggregate safety events per airport with a weighted severity score."""
        if not self._pool:
            return []
        limit = max(1, min(limit, 100))
        return await self._pool.fetch(
            """
            SELECT
                airport_icao,
                COUNT(*)::int AS incidents,
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(severity, '')) IN ('critical', 'high') THEN 3
                        WHEN LOWER(COALESCE(severity, '')) = 'medium' THEN 2
                        WHEN LOWER(COALESCE(severity, '')) = 'low' THEN 1
                        ELSE 1
                    END
                )::int AS severity_score
            FROM safety_events
            WHERE airport_icao IS NOT NULL
            GROUP BY airport_icao
            ORDER BY severity_score DESC, incidents DESC
            LIMIT $1
            """,
            limit,
        )

    async def airport_stats_view(self) -> list[asyncpg.Record]:
        """Read from airport_stats materialized view if available."""
        if not self._pool:
            return []
        return await self._pool.fetch(
            """
            SELECT icao, avg_wind, metar_count
            FROM airport_stats
            ORDER BY metar_count DESC
            LIMIT 20
            """
        )

    async def refresh_airport_stats(self) -> bool:
        """Refresh airport_stats materialized view if present."""
        if not self._pool:
            return False
        exists = await self._pool.fetchval(
            "SELECT to_regclass('public.airport_stats') IS NOT NULL"
        )
        if not exists:
            return False
        await self._pool.execute("REFRESH MATERIALIZED VIEW airport_stats")
        return True
