"""
ADS-B MCP Server - Enhanced with full FastMCP features.

Features:
- Resources: Aircraft data endpoints and reference info
- Prompts: Pre-built analysis templates for flight tracking
- Caching: SQLite-based caching (existing) + in-memory for real-time
- Lifespan: Proper startup/shutdown handling

Data Sources:
  - adsb.lol API   : real-time aircraft tracking
  - FAA Registry   : aircraft registration lookup
  - OpenSky Network: historical flight data

Usage:
    python -m adsb_mcp_server              # stdio transport
    python -m adsb_mcp_server --sse        # SSE transport
    python -m adsb_mcp_server --sse --port 9000 --host 0.0.0.0
"""

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastmcp import FastMCP
from .tools import adsb, faa, opensky

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# REAL-TIME CACHE (complements existing SQLite cache)
# ═══════════════════════════════════════════════════════════════════════════════

class RealtimeCache:
    """Short TTL cache for real-time ADS-B data."""

    def __init__(self, default_ttl: int = 60, max_size: int = 1000):
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
realtime_cache = RealtimeCache(default_ttl=60, max_size=1000)
_startup_time: Optional[datetime] = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Lifespan context manager for startup/shutdown."""
    global _startup_time

    logger.info("ADS-B MCP Server starting...")
    _startup_time = datetime.now(timezone.utc)

    # Initialize SQLite database
    try:
        from .db import init_db
        init_db()
        logger.info("SQLite database initialized")
    except Exception as e:
        logger.warning(f"Database init: {e}")

    logger.info("ADS-B MCP Server ready")
    yield
    await realtime_cache.clear()


def create_server() -> FastMCP:
    """Instantiate and configure the FastMCP server with all features."""
    mcp = FastMCP(
        name="AdsbMcpServer",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.resource("adsb://server/status")
    async def server_status() -> str:
        """Server health and cache statistics."""
        uptime = (datetime.now(timezone.utc) - _startup_time).total_seconds() if _startup_time else 0
        return json.dumps({
            "status": "healthy",
            "version": "2.0.0",
            "uptime_seconds": int(uptime),
            "realtime_cache": realtime_cache.stats(),
            "apis": ["adsb.lol", "opensky-network.org", "FAA Registry"],
        }, indent=2)

    @mcp.resource("adsb://squawk/reference")
    async def squawk_codes() -> str:
        """Emergency and special squawk code reference."""
        return json.dumps({
            "emergency": {
                "7500": {"meaning": "Hijack", "action": "DO NOT acknowledge, alert authorities"},
                "7600": {"meaning": "Radio Failure", "action": "Lost communications procedures"},
                "7700": {"meaning": "General Emergency", "action": "Priority handling"},
            },
            "special": {
                "1200": "VFR (US)",
                "7000": "VFR (Europe/ICAO)",
                "2000": "IFR entry point",
                "1000": "IFR departure",
            },
            "military": {
                "range": "0100-0400, 4400-4477",
                "intercept": "7777 (military intercept)",
            }
        }, indent=2)

    @mcp.resource("adsb://aircraft-types/common")
    async def common_aircraft() -> str:
        """Common aircraft type codes reference."""
        return json.dumps({
            "commercial": [
                {"icao": "B738", "name": "Boeing 737-800"},
                {"icao": "A320", "name": "Airbus A320"},
                {"icao": "B77W", "name": "Boeing 777-300ER"},
                {"icao": "A388", "name": "Airbus A380-800"},
                {"icao": "B789", "name": "Boeing 787-9"},
            ],
            "regional": [
                {"icao": "E190", "name": "Embraer 190"},
                {"icao": "CRJ9", "name": "Bombardier CRJ-900"},
                {"icao": "AT76", "name": "ATR 72-600"},
            ],
            "general_aviation": [
                {"icao": "C172", "name": "Cessna 172"},
                {"icao": "PA28", "name": "Piper PA-28"},
                {"icao": "SR22", "name": "Cirrus SR22"},
            ],
        }, indent=2)

    @mcp.resource("adsb://airports/icao/{icao}")
    async def airport_info(icao: str) -> str:
        """Get airport information by ICAO code."""
        # Common airports database
        airports = {
            "KJFK": {"name": "John F. Kennedy International", "city": "New York", "country": "USA"},
            "KLAX": {"name": "Los Angeles International", "city": "Los Angeles", "country": "USA"},
            "EGLL": {"name": "London Heathrow", "city": "London", "country": "UK"},
            "VHHH": {"name": "Hong Kong International", "city": "Hong Kong", "country": "China"},
            "RJTT": {"name": "Tokyo Haneda", "city": "Tokyo", "country": "Japan"},
        }
        icao = icao.upper()
        if icao in airports:
            return json.dumps({"icao": icao, **airports[icao]}, indent=2)
        return json.dumps({"icao": icao, "error": "Airport not in reference database"}, indent=2)

    # ═══════════════════════════════════════════════════════════════════════════
    # PROMPTS
    # ═══════════════════════════════════════════════════════════════════════════

    @mcp.prompt()
    async def aircraft_investigation(identifier: str) -> str:
        """Investigate an aircraft by registration or callsign."""
        return f"""Investigate aircraft: {identifier}

Steps:
1. Determine if "{identifier}" is a registration (e.g., N12345) or callsign (e.g., UAL123)
2. If registration: Use get_registration to find current position
3. If callsign: Use get_callsign to track the flight
4. Look up FAA registry with batch_lookup_faa for N-numbers
5. Get flight history with get_flights_by_aircraft (needs ICAO24 hex)

Report:
- Aircraft type and registration
- Current position and altitude
- Origin/destination if known
- Recent flight history
"""

    @mcp.prompt()
    async def airport_traffic_analysis(icao: str) -> str:
        """Analyze traffic at an airport."""
        return f"""Analyze traffic at airport: {icao}

Required:
1. get_arrivals_by_airport("{icao}") - Recent arrivals
2. get_departures_by_airport("{icao}") - Recent departures
3. get_search_radius with airport coordinates for current traffic

Analysis:
- Current inbound/outbound traffic count
- Aircraft types in operation
- Busiest routes
- Any delays or unusual patterns
"""

    @mcp.prompt()
    async def emergency_monitor(squawk: str = "7700") -> str:
        """Monitor for emergency squawk codes."""
        return f"""Monitor for emergency squawk: {squawk}

Use get_squawk("{squawk}") to find aircraft squawking emergency codes.

7500 = Hijack (alert authorities, do not acknowledge)
7600 = Radio failure (lost comms)
7700 = General emergency

Report:
- Aircraft identification
- Position and altitude
- Flight details if available
- Recommended actions
"""

    @mcp.prompt()
    async def military_activity(lat: float, lon: float, radius_nm: int = 50) -> str:
        """Monitor military aircraft activity in an area."""
        return f"""Monitor military activity around {lat}, {lon} (radius: {radius_nm}NM)

Steps:
1. get_mil() - Get current military aircraft
2. get_search_radius(lat={lat}, lon={lon}, radius_nm={radius_nm}) - Area search
3. Filter for military types (C17, KC135, F16, etc.)

Report:
- Military aircraft in area
- Types and callsigns
- Activity patterns
- Any notable operations
"""

    @mcp.prompt()
    async def flight_tracking_summary(callsign: str) -> str:
        """Get comprehensive tracking summary for a flight."""
        return f"""Track flight: {callsign}

Steps:
1. get_callsign("{callsign}") - Current position
2. get_route("{callsign}") if available - Flight route
3. Cross-reference with arrival/departure data

Summary:
- Current position, altitude, speed
- Origin and destination
- ETA if calculable
- Aircraft type
"""

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOLS
    # ═══════════════════════════════════════════════════════════════════════════

    for register_fn in [adsb.register, faa.register, opensky.register]:
        register_fn(mcp)

    @mcp.tool(description="Get cache statistics")
    async def get_adsb_cache_stats() -> str:
        """Return cache statistics for real-time and SQLite caches."""
        stats = {"realtime": realtime_cache.stats()}
        try:
            from .db import get_cache_stats
            stats["sqlite"] = get_cache_stats()
        except Exception:
            stats["sqlite"] = "unavailable"
        return json.dumps(stats, indent=2)

    @mcp.tool(description="Clear real-time cache")
    async def clear_realtime_cache() -> str:
        """Clear the real-time cache (does not affect SQLite cache)."""
        cleared = await realtime_cache.clear()
        return json.dumps({"cleared": cleared}, indent=2)

    return mcp


# Alias for consistency with other MCP servers
server = create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="ADS-B MCP Server")
    parser.add_argument("-s", "--sse", action="store_true", help="SSE mode")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host")
    args = parser.parse_args()

    sse_mode = args.sse or os.environ.get("TRANSPORT_MODE") == "sse"
    host = os.environ.get("HOST", args.host) if args.host == "127.0.0.1" else args.host
    try:
        port = int(os.environ.get("PORT", args.port)) if args.port == 8000 else args.port
    except ValueError:
        port = args.port

    mcp_server = create_server()
    if sse_mode:
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        mcp_server.run()


if __name__ == "__main__":
    main()
