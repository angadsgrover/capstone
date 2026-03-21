"""ADS-B tracking tools powered by the adsb.lol API.

Provides 11 tools for querying real-time aircraft data by squawk, callsign,
registration, ICAO hex, type, geographic radius, and special categories.
All results are persisted to the local SQLite database for downstream analysis.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import httpx
from fastmcp import FastMCP

from ..db import setup_aircraft_db

ADSB_API_BASE = "https://api.adsb.lol"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

async def _fetch(url: str) -> dict[str, Any] | None:
    """GET *url* and return the parsed JSON body, or None on any error."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                headers={"Accept": "application/geo+json"},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _save_aircraft(data: dict[str, Any], db_path: str = "aircraft.db") -> int:
    """Insert aircraft records from an adsb.lol response into *lol_aircraft*.

    Args:
        data:    Parsed API response dict (must contain an "ac" list).
        db_path: Path to the SQLite database file.

    Returns:
        Number of rows successfully inserted.
    """
    aircraft_list = data.get("ac") if data else None
    if not aircraft_list:
        return 0

    conn = setup_aircraft_db(db_path)
    cursor = conn.cursor()
    ts = int(time.time())
    count = 0

    for ac in aircraft_list:
        lp = ac.get("lastPosition") or {}
        row: dict[str, Any] = {
            "timestamp":             ts,
            "hex":                   ac.get("hex", ""),
            "alert":                 ac.get("alert"),
            "alt_baro":              str(ac.get("alt_baro", "")),
            "alt_geom":              ac.get("alt_geom"),
            "baro_rate":             ac.get("baro_rate"),
            "category":              ac.get("category"),
            "emergency":             ac.get("emergency"),
            "flight":                ac.get("flight"),
            "gs":                    ac.get("gs"),
            "gva":                   ac.get("gva"),
            "lat":                   ac.get("lat"),
            "lon":                   ac.get("lon"),
            "messages":              ac.get("messages"),
            "mlat":                  json.dumps(ac.get("mlat", [])),
            "nac_p":                 ac.get("nac_p"),
            "nac_v":                 ac.get("nac_v"),
            "nav_altitude_mcp":      ac.get("nav_altitude_mcp"),
            "nav_heading":           ac.get("nav_heading"),
            "nav_qnh":               ac.get("nav_qnh"),
            "nic":                   ac.get("nic"),
            "nic_baro":              ac.get("nic_baro"),
            "r":                     ac.get("r"),
            "rc":                    ac.get("rc"),
            "rssi":                  ac.get("rssi"),
            "sda":                   ac.get("sda"),
            "seen":                  ac.get("seen"),
            "seen_pos":              ac.get("seen_pos"),
            "sil":                   ac.get("sil"),
            "sil_type":              ac.get("sil_type"),
            "spi":                   ac.get("spi"),
            "squawk":                ac.get("squawk"),
            "t":                     ac.get("t"),
            "tisb":                  json.dumps(ac.get("tisb", [])),
            "track":                 ac.get("track"),
            "type":                  ac.get("type", ""),
            "version":               ac.get("version"),
            "geom_rate":             ac.get("geom_rate"),
            "db_flags":              ac.get("dbFlags"),
            "nav_modes":             json.dumps(ac.get("nav_modes", [])),
            "true_heading":          ac.get("true_heading"),
            "ias":                   ac.get("ias"),
            "mach":                  ac.get("mach"),
            "mag_heading":           ac.get("mag_heading"),
            "oat":                   ac.get("oat"),
            "roll":                  ac.get("roll"),
            "tas":                   ac.get("tas"),
            "tat":                   ac.get("tat"),
            "track_rate":            ac.get("track_rate"),
            "wd":                    ac.get("wd"),
            "ws":                    ac.get("ws"),
            "gps_ok_before":         ac.get("gpsOkBefore"),
            "gps_ok_lat":            ac.get("gpsOkLat"),
            "gps_ok_lon":            ac.get("gpsOkLon"),
            "last_position_lat":     lp.get("lat"),
            "last_position_lon":     lp.get("lon"),
            "last_position_nic":     lp.get("nic"),
            "last_position_rc":      lp.get("rc"),
            "last_position_seen_pos": lp.get("seen_pos"),
            "rr_lat":                ac.get("rr_lat"),
            "rr_lon":                ac.get("rr_lon"),
            "calc_track":            ac.get("calc_track"),
            "nav_altitude_fms":      ac.get("nav_altitude_fms"),
        }
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        try:
            cursor.execute(
                f"INSERT INTO lol_aircraft ({cols}) VALUES ({placeholders})",
                list(row.values()),
            )
            count += 1
        except sqlite3.Error:
            pass

    conn.commit()
    conn.close()
    return count


def _fmt_aircraft_list(ac_list: list[dict]) -> str:
    """Format a list of aircraft dicts as a readable Markdown string."""
    parts = []
    for ac in ac_list:
        lines = [f"**{k}**: {v}" for k, v in ac.items() if v is not None and v != ""]
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:
    """Attach all adsb.lol tools to *mcp*."""

    @mcp.tool(
        description=(
            "Returns all aircraft currently using Privacy ICAO Address (PIA). "
            "PIA addresses are used to conceal the identity of private aircraft. "
            "Saves results to the local database and returns the count."
        )
    )
    async def get_pia() -> str:
        data = await _fetch(f"{ADSB_API_BASE}/v2/pia")
        if not data or not data.get("ac"):
            return "No PIA aircraft found."
        count = _save_aircraft(data)
        return f"Found and saved {count} PIA aircraft to database."

    @mcp.tool(
        description=(
            "Returns all military-registered aircraft currently being tracked. "
            "Saves results to the local database and returns the count."
        )
    )
    async def get_mil() -> str:
        data = await _fetch(f"{ADSB_API_BASE}/v2/mil")
        if not data or not data.get("ac"):
            return "No military aircraft found."
        count = _save_aircraft(data)
        return f"Found and saved {count} military aircraft to database."

    @mcp.tool(
        description=(
            "Returns all aircraft enrolled in the FAA Limiting Aircraft Data "
            "Displayed (LADD) program, which restricts their public tracking. "
            "Saves results to the local database and returns the count."
        )
    )
    async def get_ladd() -> str:
        data = await _fetch(f"{ADSB_API_BASE}/v2/ladd")
        if not data or not data.get("ac"):
            return "No LADD aircraft found."
        count = _save_aircraft(data)
        return f"Found and saved {count} LADD aircraft to database."

    @mcp.tool(
        description=(
            "Returns aircraft currently broadcasting the given transponder squawk "
            "code (e.g. '7700' for emergency, '7600' for radio failure). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_squawk(squawk: str) -> str:
        """
        Args:
            squawk: Four-digit octal transponder code to search for.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/sqk/{squawk}")
        if not data or not data.get("ac"):
            return f"No aircraft found with squawk code '{squawk}'."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return f"Found {count} aircraft with squawk '{squawk}'.\n\n{formatted}"

    @mcp.tool(
        description=(
            "Returns aircraft filtered by ICAO aircraft type designator code "
            "(e.g. 'B738' for Boeing 737-800, 'A320' for Airbus A320). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_type(aircraft_type: str) -> str:
        """
        Args:
            aircraft_type: ICAO type designator such as B738, A320, or C172.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/type/{aircraft_type}")
        if not data or not data.get("ac"):
            return f"No aircraft found of type '{aircraft_type}'."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return f"Found {count} aircraft of type '{aircraft_type}'.\n\n{formatted}"

    @mcp.tool(
        description=(
            "Returns aircraft filtered by tail number / registration "
            "(e.g. 'N12345' for US, 'G-KELS' for UK). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_registration(registration: str) -> str:
        """
        Args:
            registration: Aircraft registration / tail number.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/reg/{registration}")
        if not data or not data.get("ac"):
            return f"No aircraft found with registration '{registration}'."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return f"Found {count} aircraft with registration '{registration}'.\n\n{formatted}"

    @mcp.tool(
        description=(
            "Returns aircraft filtered by ICAO 24-bit Mode-S transponder hex code "
            "(e.g. 'a1b2c3'). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_icao_hex(icao_hex: str) -> str:
        """
        Args:
            icao_hex: Six-character hexadecimal Mode-S transponder code.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/icao/{icao_hex}")
        if not data or not data.get("ac"):
            return f"No aircraft found with ICAO hex '{icao_hex}'."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return f"Found {count} aircraft with ICAO hex '{icao_hex}'.\n\n{formatted}"

    @mcp.tool(
        description=(
            "Returns aircraft filtered by flight callsign "
            "(e.g. 'UAL123', 'BAW456', or 'N12345' for general aviation). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_callsign(callsign: str) -> str:
        """
        Args:
            callsign: ICAO or IATA flight callsign.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/callsign/{callsign}")
        if not data or not data.get("ac"):
            return f"No aircraft found with callsign '{callsign}'."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return f"Found {count} aircraft with callsign '{callsign}'.\n\n{formatted}"

    @mcp.tool(
        description=(
            "Returns all aircraft within a circular area defined by a center "
            "latitude/longitude and a radius in nautical miles. "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_search_radius(lat: float, lon: float, radius: float) -> str:
        """
        Args:
            lat:    Latitude of the center point in decimal degrees.
            lon:    Longitude of the center point in decimal degrees.
            radius: Search radius in nautical miles.
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/point/{lat}/{lon}/{radius}")
        if not data or not data.get("ac"):
            return f"No aircraft found within {radius}nm of ({lat}, {lon})."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return (
            f"Found {count} aircraft within {radius}nm of ({lat}, {lon}).\n\n{formatted}"
        )

    @mcp.tool(
        description=(
            "Returns the closest aircraft to a given lat/lon point, searching "
            "within a specified radius (up to 250 nm). "
            "Saves results to the local database and returns full aircraft details."
        )
    )
    async def get_closest(lat: float, lon: float, radius: float) -> str:
        """
        Args:
            lat:    Latitude of the reference point in decimal degrees.
            lon:    Longitude of the reference point in decimal degrees.
            radius: Maximum search radius in nautical miles (max 250).
        """
        data = await _fetch(f"{ADSB_API_BASE}/v2/closest/{lat}/{lon}/{radius}")
        if not data or not data.get("ac"):
            return f"No aircraft found within {radius}nm of ({lat}, {lon})."
        count = _save_aircraft(data)
        formatted = _fmt_aircraft_list(data["ac"])
        return (
            f"Found {count} closest aircraft within {radius}nm of ({lat}, {lon}).\n\n{formatted}"
        )

    @mcp.tool(
        description=(
            "Returns route information (departure and destination airports) for a "
            "flight identified by its callsign, using the adsb.lol route database."
        )
    )
    async def get_route(callsign: str) -> str:
        """
        Args:
            callsign: Flight callsign to look up (e.g. 'UAL123').
        """
        data = await _fetch(f"{ADSB_API_BASE}/v0/route/{callsign}")
        if not data:
            return f"No route found for callsign '{callsign}'."
        return json.dumps(data, indent=2)
