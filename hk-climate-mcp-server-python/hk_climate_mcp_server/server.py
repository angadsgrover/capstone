"""
HK Climate MCP Server - Enhanced with full FastMCP features.

Features:
- Resources: HKO data endpoints and reference info
- Prompts: Pre-built analysis templates for HK weather
- Caching: TTL-based caching for HKO API responses
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

from .tools import current_weather, warnings, visibility, forecast
from .service import HKClimateService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CACHING
# ═══════════════════════════════════════════════════════════════════════════════

class TTLCache:
    """TTL-based in-memory cache for HKO data."""

    def __init__(self, default_ttl: int = 600, max_size: int = 100):
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        import time
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
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
hko_cache = TTLCache(default_ttl=600, max_size=100)  # 10 min TTL
_climate_service: Optional[HKClimateService] = None
_startup_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Lifespan context manager for startup/shutdown."""
    global _climate_service, _startup_time

    logger.info("HK Climate MCP Server starting...")
    _startup_time = datetime.now(timezone.utc)
    _climate_service = HKClimateService()

    # Pre-warm with current weather
    try:
        data = await _climate_service.get_current_weather("en")
        if data:
            await hko_cache.set("current:en", data)
            logger.info("Pre-warmed current weather cache")
    except Exception:
        pass

    logger.info("HK Climate MCP Server ready")
    yield
    await hko_cache.clear()


def server():
    """Create and configure the HK Climate MCP server."""
    mcp = FastMCP(
        name="HKClimateServer",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.resource("hko://server/status")
    async def server_status() -> str:
        """Server health and cache statistics."""
        uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds() if _startup_time else 0
        return json.dumps({
            "status": "healthy",
            "version": "2.0.0",
            "uptime_seconds": int(uptime),
            "cache": hko_cache.stats(),
            "api": "data.weather.gov.hk",
        }, indent=2)

    @mcp.resource("hko://warnings/types")
    async def warning_types() -> str:
        """HKO warning signal types reference."""
        return json.dumps({
            "tropical_cyclone": {
                "signals": ["T1", "T3", "T8NE", "T8SE", "T8NW", "T8SW", "T9", "T10"],
                "description": "Typhoon warning signals",
            },
            "rainstorm": {
                "signals": ["AMBER", "RED", "BLACK"],
                "description": "Rainstorm warning signals",
            },
            "other": [
                "WFROST", "WCOLD", "WHOT", "WMSGNL", "WTMW", "WTS",
                "WFIRE", "WFNTSA", "WFNTSE", "WFNTSW"
            ],
        }, indent=2)

    @mcp.resource("hko://stations")
    async def weather_stations() -> str:
        """HKO weather observation stations."""
        return json.dumps({
            "stations": [
                {"name": "Hong Kong Observatory", "code": "HKO", "district": "Kowloon"},
                {"name": "Tai Mo Shan", "code": "TMS", "district": "New Territories"},
                {"name": "Waglan Island", "code": "WGL", "district": "Outlying Islands"},
                {"name": "Cheung Chau", "code": "CCH", "district": "Outlying Islands"},
                {"name": "Sha Tin", "code": "SHA", "district": "New Territories"},
                {"name": "Sai Kung", "code": "SKG", "district": "New Territories"},
                {"name": "Tseung Kwan O", "code": "TKO", "district": "New Territories"},
                {"name": "Happy Valley", "code": "HV", "district": "Hong Kong Island"},
            ]
        }, indent=2)

    @mcp.resource("hko://current/{lang}")
    async def cached_current(lang: str = "en") -> str:
        """Get cached or fresh current weather."""
        cached = await hko_cache.get(f"current:{lang}")
        if cached:
            return json.dumps({"source": "cache", "data": cached}, indent=2)
        if _climate_service:
            try:
                data = await _climate_service.get_current_weather(lang)
                if data:
                    await hko_cache.set(f"current:{lang}", data)
                    return json.dumps({"source": "live", "data": data}, indent=2)
            except Exception as e:
                return json.dumps({"error": str(e)}, indent=2)
        return json.dumps({"error": "Service unavailable"}, indent=2)

    @mcp.resource("hko://warnings/active")
    async def active_warnings() -> str:
        """Get currently active weather warnings."""
        cached = await hko_cache.get("warnings:active")
        if cached:
            return json.dumps({"source": "cache", "data": cached}, indent=2)
        if _climate_service:
            try:
                data = await _climate_service.get_warnings()
                if data:
                    await hko_cache.set("warnings:active", data, ttl=300)  # 5 min for warnings
                    return json.dumps({"source": "live", "data": data}, indent=2)
            except Exception as e:
                return json.dumps({"error": str(e)}, indent=2)
        return json.dumps({"error": "Service unavailable"}, indent=2)

    # ═══════════════════════════════════════════════════════════════════════════
    # PROMPTS
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.prompt()
    async def typhoon_briefing() -> str:
        """Generate a comprehensive typhoon situation briefing."""
        return """You are a Hong Kong weather analyst providing a typhoon briefing.

Required Actions:
1. get_weather_warnings - Check for active typhoon signals (T1/T3/T8/T9/T10)
2. get_current_weather - Current conditions
3. get_weather_forecast - Track and forecast
4. get_visibility_data - Visibility conditions
5. rag_search with source_type='safety' for historical typhoon impacts

Briefing Structure:
- Current Signal: Active warning level
- Storm Details: Position, movement, intensity
- Local Impact: Wind, rain, visibility
- Precautions: Based on signal level
- Forecast: Expected changes in next 6-12 hours
"""

    @mcp.prompt()
    async def rainstorm_analysis() -> str:
        """Analyze rainstorm conditions and impacts."""
        return """Analyze current rainstorm conditions in Hong Kong.

Required:
1. get_weather_warnings - Check AMBER/RED/BLACK rainstorm warnings
2. get_current_weather - Rainfall data
3. get_visibility_data - Current visibility
4. rag_search for similar historical rainstorm events

Report: Warning level, rainfall intensity, flooding risk, travel impacts, school/work arrangements.
"""

    @mcp.prompt()
    async def hk_flight_conditions() -> str:
        """Assess conditions for flights to/from Hong Kong."""
        return """Assess flight conditions for Hong Kong International Airport (VHHH).

Required:
1. get_current_weather - Temperature, pressure, wind
2. get_visibility_data - Runway visibility
3. get_weather_warnings - Any active warnings affecting aviation
4. get_weather_forecast - Trend for next 12 hours

Report: Current ceiling, visibility, wind, any weather affecting operations, forecast changes.
Note: For VHHH METAR/TAF, the aviation_weather server should be used.
"""

    @mcp.prompt()
    async def outdoor_activity_advisory(activity: str = "hiking") -> str:
        """Provide weather advisory for outdoor activities."""
        return f"""Provide weather advisory for {activity} in Hong Kong.

Required:
1. get_current_weather - Conditions
2. get_weather_warnings - Active warnings
3. get_weather_forecast - Next 9 days
4. get_visibility_data - Visibility

Advisory for {activity}:
- Current conditions suitability
- Heat/cold stress warnings
- UV index and sun protection
- Rain probability
- Recommendation (GO/CAUTION/NO-GO)
"""

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOLS
    # ═══════════════════════════════════════════════════════════════════════════

    for tool_register in [
        current_weather.register,
        warnings.register,
        visibility.register,
        forecast.register,
    ]:
        tool_register(mcp)

    @mcp.tool(description="Get HKO cache statistics")
    async def get_hko_cache_stats() -> str:
        return json.dumps({"hko_cache": hko_cache.stats()}, indent=2)

    @mcp.tool(description="Clear HKO cache")
    async def clear_hko_cache() -> str:
        cleared = await hko_cache.clear()
        return json.dumps({"cleared": cleared}, indent=2)

    return mcp