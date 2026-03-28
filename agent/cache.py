"""
Redis cache manager for high-performance query caching.

Caches:
1. **Common queries**: METAR/TAF for popular airports (TTL: 15 min)
2. **RAG search results**: Historical weather/safety data (TTL: 1 hour)
3. **Knowledge graph searches**: Domain knowledge (TTL: 24 hours)
4. **LLM responses**: Full agent responses (TTL: 5 min, context-aware)

Architecture:
  Agent Query → Cache Check → [HIT: return cached | MISS: compute + cache]

Best Practices:
1. **Cache Keys**: Deterministic, include all context (query + session + route)
2. **TTL Strategy**: Shorter for real-time data, longer for static knowledge
3. **Invalidation**: Automatic expiry + manual invalidation for ingestion
4. **Compression**: Use msgpack for structured data (faster than JSON)
5. **Graceful Degradation**: Cache failures never crash; log + continue

Configuration:
  REDIS_URL=redis://localhost:6379/0  # Redis connection string
  CACHE_ENABLED=true                   # Enable/disable caching (default: true)
  CACHE_TTL_WEATHER=900                # Weather cache TTL (seconds, default: 15 min)
  CACHE_TTL_RAG=3600                   # RAG cache TTL (seconds, default: 1 hour)
  CACHE_TTL_KNOWLEDGE=86400            # Knowledge graph TTL (seconds, default: 24 hours)
  CACHE_TTL_LLM=300                    # LLM response TTL (seconds, default: 5 min)

Example (.env):
  REDIS_URL=redis://localhost:6379/0
  CACHE_ENABLED=true
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Parse integer env vars safely, tolerating inline comments and spaces."""
    raw = os.getenv(name)
    if raw is None:
        return default

    # Accept values like "900 # 15 min" from .env files with inline comments.
    candidate = raw.split("#", 1)[0].strip()
    if not candidate:
        return default

    try:
        return int(candidate)
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to %d", name, raw, default)
        return default


def _should_enable_cache() -> bool:
    """Check if cache should be enabled based on environment."""
    if os.getenv("CACHE_ENABLED", "true").lower() == "false":
        return False
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.info("Cache disabled: REDIS_URL not set.")
        return False
    return True


class CacheManager:
    """
    Redis-backed cache manager with automatic TTL and graceful degradation.

    Usage:
        cache = CacheManager()
        await cache.init()

        # Check cache
        result = await cache.get("weather:EGLL")
        if result is None:
            result = fetch_weather("EGLL")
            await cache.set("weather:EGLL", result, ttl=900)

        # Invalidate
        await cache.delete("weather:EGLL")
        await cache.clear_pattern("weather:*")  # all weather caches
    """

    def __init__(self) -> None:
        self._redis: Any = None
        self._enabled = _should_enable_cache()

        # TTL defaults (seconds)
        self.ttl_weather = _env_int("CACHE_TTL_WEATHER", 900)      # 15 min
        self.ttl_rag = _env_int("CACHE_TTL_RAG", 3600)            # 1 hour
        self.ttl_knowledge = _env_int("CACHE_TTL_KNOWLEDGE", 86400)  # 24 hours
        self.ttl_llm = _env_int("CACHE_TTL_LLM", 300)             # 5 min

    async def init(self) -> None:
        """Initialize Redis connection."""
        if not self._enabled:
            logger.info("Cache disabled (CACHE_ENABLED=false or missing REDIS_URL).")
            return

        try:
            import redis.asyncio as redis

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self._redis = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

            # Test connection
            await self._redis.ping()
            logger.info("Redis cache initialized: %s", redis_url)
        except ImportError:
            logger.warning("redis package not installed; cache disabled.")
            self._enabled = False
        except Exception as e:
            logger.warning("Redis connection failed: %s — cache disabled.", e)
            self._enabled = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.debug("Redis close error: %s", e)

    @property
    def available(self) -> bool:
        """Check if cache is available."""
        return self._enabled and self._redis is not None

    # ── Core operations ───────────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value (deserialized), or None if miss/error
        """
        if not self.available:
            return None

        try:
            value = await self._redis.get(key)
            if value is None:
                return None

            # Deserialize JSON
            return json.loads(value)
        except Exception as e:
            logger.debug("Cache get error (key=%s): %s", key, e)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Store value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time-to-live in seconds (None = no expiry)

        Returns:
            True if successful, False otherwise
        """
        if not self.available:
            return False

        try:
            # Serialize to JSON
            serialized = json.dumps(value, default=str)

            if ttl:
                await self._redis.setex(key, ttl, serialized)
            else:
                await self._redis.set(key, serialized)

            return True
        except Exception as e:
            logger.debug("Cache set error (key=%s): %s", key, e)
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False otherwise
        """
        if not self.available:
            return False

        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.debug("Cache delete error (key=%s): %s", key, e)
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern.

        Args:
            pattern: Redis pattern (e.g., "weather:*", "rag:*")

        Returns:
            Number of keys deleted
        """
        if not self.available:
            return 0

        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await self._redis.delete(*keys)
                logger.info("Cleared %d cache keys matching: %s", len(keys), pattern)
                return len(keys)
            return 0
        except Exception as e:
            logger.debug("Cache clear_pattern error (pattern=%s): %s", pattern, e)
            return 0

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        if not self.available:
            return False

        try:
            return bool(await self._redis.exists(key))
        except Exception as e:
            logger.debug("Cache exists error (key=%s): %s", key, e)
            return False

    # ── High-level helpers ────────────────────────────────────────────────────

    def make_key(self, prefix: str, *parts: str) -> str:
        """
        Generate deterministic cache key from parts.

        Args:
            prefix: Key prefix (e.g., "weather", "rag", "knowledge")
            parts: Key components (will be hashed together)

        Returns:
            Cache key: "{prefix}:{hash}"

        Example:
            make_key("weather", "EGLL", "METAR") → "weather:a3f8d9e2"
            make_key("llm", query, session_id, route) → "llm:b4c7f1a9"
        """
        combined = ":".join(str(p) for p in parts)
        key_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]
        return f"{prefix}:{key_hash}"

    async def get_or_compute(
        self,
        key: str,
        compute_fn,
        ttl: Optional[int] = None,
    ) -> Any:
        """
        Get from cache, or compute and cache if miss.

        Args:
            key: Cache key
            compute_fn: Async function to compute value on cache miss
            ttl: TTL for cached value

        Returns:
            Cached or computed value

        Example:
            result = await cache.get_or_compute(
                "weather:EGLL",
                lambda: fetch_weather("EGLL"),
                ttl=900
            )
        """
        # Try cache first
        cached = await self.get(key)
        if cached is not None:
            logger.debug("Cache HIT: %s", key)
            return cached

        # Cache miss: compute
        logger.debug("Cache MISS: %s", key)
        result = await compute_fn()

        # Cache result
        await self.set(key, result, ttl=ttl)
        return result

    async def mget(self, keys: list[str]) -> list[Optional[Any]]:
        """
        Batch get using Redis pipelining for lower round-trip latency.

        Returns list aligned with input keys. Missing/error items are None.
        """
        if not self.available or not keys:
            return [None for _ in keys]
        try:
            pipe = self._redis.pipeline()
            for key in keys:
                pipe.get(key)
            raw_values = await pipe.execute()
            return [json.loads(v) if v is not None else None for v in raw_values]
        except Exception as e:
            logger.debug("Cache mget error: %s", e)
            return [None for _ in keys]

    async def mset(
        self,
        items: dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Batch set using Redis pipelining.
        """
        if not self.available or not items:
            return False
        try:
            pipe = self._redis.pipeline()
            for key, value in items.items():
                serialized = json.dumps(value, default=str)
                if ttl:
                    pipe.setex(key, ttl, serialized)
                else:
                    pipe.set(key, serialized)
            await pipe.execute()
            return True
        except Exception as e:
            logger.debug("Cache mset error: %s", e)
            return False

    # ── Domain-specific helpers ───────────────────────────────────────────────

    async def get_weather(self, icao: str, weather_type: str = "METAR") -> Optional[str]:
        """Get cached weather data (METAR/TAF)."""
        key = self.make_key("weather", icao, weather_type)
        return await self.get(key)

    async def set_weather(
        self,
        icao: str,
        weather_type: str,
        data: str,
    ) -> bool:
        """Cache weather data with 15-minute TTL."""
        key = self.make_key("weather", icao, weather_type)
        return await self.set(key, data, ttl=self.ttl_weather)

    async def get_rag_search(self, query: str, source_type: str = "all") -> Optional[list]:
        """Get cached RAG search results."""
        key = self.make_key("rag", query, source_type)
        return await self.get(key)

    async def set_rag_search(
        self,
        query: str,
        source_type: str,
        results: list,
    ) -> bool:
        """Cache RAG search results with 1-hour TTL."""
        key = self.make_key("rag", query, source_type)
        return await self.set(key, results, ttl=self.ttl_rag)

    async def get_knowledge_search(
        self,
        query: str,
        dataset: str = "aviation_knowledge",
    ) -> Optional[str]:
        """Get cached knowledge graph search."""
        key = self.make_key("knowledge", query, dataset)
        return await self.get(key)

    async def set_knowledge_search(
        self,
        query: str,
        dataset: str,
        results: str,
    ) -> bool:
        """Cache knowledge graph search with 24-hour TTL."""
        key = self.make_key("knowledge", query, dataset)
        return await self.set(key, results, ttl=self.ttl_knowledge)

    async def get_llm_response(
        self,
        query: str,
        session_id: str,
        route: str,
    ) -> Optional[str]:
        """
        Get cached LLM response (context-aware).

        Cache key includes route to handle context differences.
        """
        key = self.make_key("llm", query, session_id, route)
        return await self.get(key)

    async def set_llm_response(
        self,
        query: str,
        session_id: str,
        route: str,
        response: str,
    ) -> bool:
        """Cache LLM response with 5-minute TTL."""
        key = self.make_key("llm", query, session_id, route)
        return await self.set(key, response, ttl=self.ttl_llm)

    async def invalidate_knowledge_cache(self) -> int:
        """Invalidate all knowledge graph caches (e.g., after document ingestion)."""
        return await self.clear_pattern("knowledge:*")

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        if not self.available:
            return {"available": False}

        try:
            info = await self._redis.info("stats")
            return {
                "available": True,
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": (
                    info.get("keyspace_hits", 0) /
                    (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1))
                ),
            }
        except Exception as e:
            logger.debug("Cache stats error: %s", e)
            return {"available": True, "error": str(e)}

    # ── Distributed rate limiting helpers ────────────────────────────────────

    async def check_rate_limit(
        self,
        bucket: str,
        subject: str,
        limit: int,
        window_seconds: int,
    ) -> dict[str, Any]:
        """
        Sliding-window-ish fixed bucket limiter using Redis INCR + EXPIRE.

        Returns:
            {
                "allowed": bool,
                "count": int,
                "remaining": int,
                "retry_after": int,
                "limit": int,
                "window_seconds": int,
                "key": str,
            }
        """
        key = self.make_key("rl", bucket, subject, str(window_seconds))

        if not self.available:
            # Graceful degradation: if Redis is unavailable, do not hard-block.
            return {
                "allowed": True,
                "count": 0,
                "remaining": limit,
                "retry_after": 0,
                "limit": limit,
                "window_seconds": window_seconds,
                "key": key,
            }

        try:
            count = int(await self._redis.incr(key))
            if count == 1:
                await self._redis.expire(key, window_seconds)

            ttl = int(await self._redis.ttl(key))
            retry_after = max(ttl, 0)
            allowed = count <= limit
            remaining = max(limit - count, 0)

            return {
                "allowed": allowed,
                "count": count,
                "remaining": remaining,
                "retry_after": retry_after,
                "limit": limit,
                "window_seconds": window_seconds,
                "key": key,
            }
        except Exception as e:
            logger.debug("Rate-limit check error (bucket=%s): %s", bucket, e)
            return {
                "allowed": True,
                "count": 0,
                "remaining": limit,
                "retry_after": 0,
                "limit": limit,
                "window_seconds": window_seconds,
                "key": key,
                "error": str(e),
            }
