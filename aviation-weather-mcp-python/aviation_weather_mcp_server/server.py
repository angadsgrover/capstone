"""
Aviation Weather MCP Server - Enhanced with full FastMCP features.

Features:
- Resources: Static and dynamic data endpoints
- Prompts: Pre-built analysis templates
- Caching: TTL-based caching for API responses
- Lifespan: Proper startup/shutdown handling
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from .tools import weather, flight_route, analysis, airport, prompts
from .service import AviationWeatherService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CACHING
# ═══════════════════════════════════════════════════════════════════════════════

class TTLCache:
    """TTL-based in-memory cache for weather data."""

    def __init__(self, default_ttl: int = 300, max_size: int = 500):
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                import time
                if time.time() < expiry:
                    self._hits += 1
                    return value
                del self._cache[key]
            self._misses += 1
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        import time
        async with self._lock:
            if len(self._cache) >= self._max_size:
                to_remove = sorted(self._cache.items(), key=lambda x: x[1][1])[:self._max_size // 10]
                for k, _ in to_remove:
                    del self._cache[k]
            self._cache[key] = (value, time.time() + (ttl or self._default_ttl))

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{(self._hits / total * 100):.1f}%" if total > 0 else "N/A",
        }


# Global instances
metar_cache = TTLCache(default_ttl=300, max_size=500)
taf_cache = TTLCache(default_ttl=1800, max_size=200)
_weather_service: Optional[AviationWeatherService] = None
_startup_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Lifespan context manager for startup/shutdown."""
    global _weather_service, _startup_time

    logger.info("Aviation Weather MCP Server starting...")
    _startup_time = datetime.now(timezone.utc)
    _weather_service = AviationWeatherService()

    prewarm = os.environ.get("PREWARM_STATIONS", "").split(",")
    if prewarm and prewarm[0]:
        for station in prewarm[:5]:
            try:
                data = await _weather_service.get_metar(station.strip(), hours_back=1)
                if data:
                    await metar_cache.set(f"metar:{station.strip()}", data)
            except Exception:
                pass

    logger.info("Aviation Weather MCP Server ready")
    yield
    await metar_cache.clear()
    await taf_cache.clear()


def server():
    """Create and configure the Aviation Weather MCP server."""
    mcp = FastMCP(
        name="AviationWeatherServer",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.resource("aviation://server/status")
    async def server_status() -> str:
        """Server health and cache statistics."""
        uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds() if _startup_time else 0
        return json.dumps({
            "status": "healthy", "version": "2.0.0", "uptime_seconds": int(uptime),
            "metar_cache": metar_cache.stats(), "taf_cache": taf_cache.stats(),
        }, indent=2)

    @mcp.resource("aviation://airports/major")
    async def major_airports() -> str:
        """Major international airports reference."""
        return json.dumps({"airports": [
            {"icao": "KJFK", "name": "New York JFK"},
            {"icao": "KLAX", "name": "Los Angeles"},
            {"icao": "EGLL", "name": "London Heathrow"},
            {"icao": "VHHH", "name": "Hong Kong"},
            {"icao": "RJTT", "name": "Tokyo Haneda"},
            {"icao": "OMDB", "name": "Dubai"},
        ]}, indent=2)

    @mcp.resource("aviation://categories/reference")
    async def flight_categories_ref() -> str:
        """Flight category definitions."""
        return json.dumps({
            "VFR": {"ceiling": ">3000ft", "visibility": ">5SM", "color": "green"},
            "MVFR": {"ceiling": "1000-3000ft", "visibility": "3-5SM", "color": "blue"},
            "IFR": {"ceiling": "500-1000ft", "visibility": "1-3SM", "color": "red"},
            "LIFR": {"ceiling": "<500ft", "visibility": "<1SM", "color": "magenta"},
        }, indent=2)

    @mcp.resource("aviation://metar/{station}")
    async def cached_metar(station: str) -> str:
        """Get cached or fresh METAR."""
        station = station.upper()
        cached = await metar_cache.get(f"metar:{station}")
        if cached:
            return json.dumps({"source": "cache", "data": cached}, indent=2)
        if _weather_service:
            try:
                data = await _weather_service.get_metar(station, hours_back=1)
                if data:
                    result = [{"raw": m.raw, "station": m.station} for m in data]
                    await metar_cache.set(f"metar:{station}", result)
                    return json.dumps({"source": "live", "data": result}, indent=2)
            except Exception as e:
                return json.dumps({"error": str(e)}, indent=2)
        return json.dumps({"error": "Service unavailable"}, indent=2)

    # ═══════════════════════════════════════════════════════════════════════════
    # PROMPTS
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.prompt()
    async def preflight_briefing(departure: str, destination: str, alternate: str = "") -> str:
        """Generate a pre-flight weather briefing."""
        return f"""You are an aviation meteorologist preparing a pre-flight briefing.

Airports: {departure} -> {destination}{f" (alt: {alternate})" if alternate else ""}

Required:
1. get_metar for all airports
2. get_taf for all airports
3. get_pireps along the route
4. get_airmets for the region
5. rag_search for historical patterns

Output: Synopsis, Departure, En Route, Destination, Hazards, GO/NO-GO recommendation."""

    @mcp.prompt()
    async def ifr_alternate_check(destination: str, alternate: str) -> str:
        """Check IFR alternate requirements per FAR 91.169."""
        return f"""Check IFR alternate legality:
Destination: {destination}, Alternate: {alternate}

Get TAF for both. Verify alternate has ceiling 600ft above minimums and visibility 2SM above minimums for ETA +/- 1 hour."""

    @mcp.prompt()
    async def severe_weather_analysis(region: str = "CONUS") -> str:
        """Analyze severe weather in a region."""
        return f"""Analyze severe weather for: {region}

Get AIRMETs, PIREPs (turbulence/icing), and use rag_search for similar events.
Report hazards, severity, coverage, movement, and avoidance recommendations."""

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOLS
    # ═══════════════════════════════════════════════════════════════════════════

    for tool_register in [
        weather.register,
        flight_route.register,
        analysis.register,
        airport.register,
        prompts.register,
    ]:
        tool_register(mcp)

    @mcp.tool(description="Get cache statistics")
    async def get_cache_stats() -> str:
        return json.dumps({"metar": metar_cache.stats(), "taf": taf_cache.stats()}, indent=2)

    @mcp.tool(description="Clear weather caches")
    async def clear_weather_cache() -> str:
        m, t = await metar_cache.clear(), await taf_cache.clear()
        return json.dumps({"cleared": {"metar": m, "taf": t}}, indent=2)

    return mcp