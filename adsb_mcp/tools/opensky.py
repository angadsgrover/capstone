"""OpenSky Network tools.

Provides 7 async tools that query the OpenSky Network REST API and cache
responses locally in SQLite for 1 hour to avoid repeated requests:

  - get_states               : live state vectors for all/filtered aircraft
  - get_my_states            : state vectors from your own sensors (auth required)
  - get_arrivals_by_airport  : recent arrivals at an airport
  - get_departures_by_airport: recent departures from an airport
  - get_flights_by_aircraft  : flight history for a specific aircraft
  - get_flights_from_interval: all flights in a time window
  - get_track_by_aircraft    : flight trajectory / track

All requests use the public OpenSky REST API at https://opensky-network.org/api.
Authenticated access (username + password) enables higher rate limits and the
get_my_states tool.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from typing import Any

import httpx
from fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db import setup_aircraft_db

OPENSKY_BASE = "https://opensky-network.org/api"
CACHE_TTL = 3600  # seconds


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

async def _opensky_get(
    path: str,
    params: dict[str, Any],
    username: str | None = None,
    password: str | None = None,
) -> Any:
    """GET ``OPENSKY_BASE + path`` with optional basic-auth.

    Returns the parsed JSON body or None on any error.
    """
    auth = (username, password) if username and password else None
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{OPENSKY_BASE}{path}",
                params={k: v for k, v in params.items() if v is not None},
                auth=auth,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# States cache helpers
# ---------------------------------------------------------------------------

def _cache_key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True)


def _is_cached(cursor, params_json: str, api_type: str) -> tuple[bool, int | None]:
    cursor.execute(
        "SELECT timestamp, api_response_time FROM opensky_requests_cache "
        "WHERE params_json = ? AND api_type = ?",
        (params_json, api_type),
    )
    row = cursor.fetchone()
    if row and (time.time() - row[0] < CACHE_TTL):
        return True, row[1]
    return False, None


def _invalidate(cursor, params_json: str) -> None:
    cursor.execute(
        "DELETE FROM opensky_requests_cache WHERE params_json = ?",
        (params_json,),
    )


def _insert_request(cursor, params_json: str, api_type: str, api_ts: int) -> None:
    cursor.execute(
        "INSERT INTO opensky_requests_cache (params_json, api_type, timestamp, api_response_time) "
        "VALUES (?, ?, ?, ?)",
        (params_json, api_type, int(time.time()), api_ts),
    )


def _store_states(cursor, params_json: str, raw: dict) -> None:
    """Persist raw OpenSky states response to *opensky_states_data*."""
    for sv in raw.get("states") or []:
        # REST API returns a 17/18-element array per state vector
        if not isinstance(sv, (list, tuple)) or len(sv) < 17:
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO opensky_states_data (
                request_params_json, icao24, last_contact, callsign, origin_country,
                time_position, longitude, latitude, baro_altitude, on_ground,
                velocity, true_track, vertical_rate, sensors, geo_altitude,
                squawk, spi, position_source, category
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                params_json,
                sv[0],                                        # icao24
                sv[4],                                        # last_contact
                sv[1],                                        # callsign
                sv[2],                                        # origin_country
                sv[3],                                        # time_position
                sv[5],                                        # longitude
                sv[6],                                        # latitude
                sv[7],                                        # baro_altitude
                1 if sv[8] else 0,                            # on_ground
                sv[9],                                        # velocity
                sv[10],                                       # true_track
                sv[11],                                       # vertical_rate
                json.dumps(sv[12]) if sv[12] else None,       # sensors
                sv[13],                                       # geo_altitude
                sv[14],                                       # squawk
                1 if sv[15] else 0,                           # spi
                sv[16],                                       # position_source
                sv[17] if len(sv) > 17 else None,             # category
            ),
        )


def _load_states(cursor, params_json: str, api_ts: int) -> dict:
    cursor.execute(
        "SELECT * FROM opensky_states_data WHERE request_params_json = ?",
        (params_json,),
    )
    cols = [d[0] for d in cursor.description]
    states = [dict(zip(cols, row)) for row in cursor.fetchall()]
    return {"time": api_ts, "states": states}


# ---------------------------------------------------------------------------
# Flights cache helpers
# ---------------------------------------------------------------------------

def _store_flights(cursor, params_json: str, flights: list[dict]) -> None:
    for f in flights or []:
        cursor.execute(
            """
            INSERT OR REPLACE INTO opensky_flights_data (
                request_params_json, icao24, firstSeen, callsign,
                estDepartureAirport, lastSeen, estArrivalAirport,
                estDepartureAirportHorizDistance, estDepartureAirportVertDistance,
                estArrivalAirportHorizDistance, estArrivalAirportVertDistance,
                departureAirportCandidatesCount, arrivalAirportCandidatesCount
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                params_json,
                f.get("icao24"),
                f.get("firstSeen"),
                f.get("callsign"),
                f.get("estDepartureAirport"),
                f.get("lastSeen"),
                f.get("estArrivalAirport"),
                f.get("estDepartureAirportHorizDistance"),
                f.get("estDepartureAirportVertDistance"),
                f.get("estArrivalAirportHorizDistance"),
                f.get("estArrivalAirportVertDistance"),
                f.get("departureAirportCandidatesCount"),
                f.get("arrivalAirportCandidatesCount"),
            ),
        )


def _load_flights(cursor, params_json: str) -> list[dict]:
    cursor.execute(
        "SELECT * FROM opensky_flights_data WHERE request_params_json = ?",
        (params_json,),
    )
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Track cache helpers
# ---------------------------------------------------------------------------

def _store_track(cursor, params_json: str, track: dict) -> None:
    cursor.execute(
        "INSERT OR REPLACE INTO opensky_tracks_data "
        "(request_params_json, icao24, startTime, endTime, callsign) "
        "VALUES (?,?,?,?,?)",
        (
            params_json,
            track.get("icao24"),
            track.get("startTime"),
            track.get("endTime"),
            track.get("callsign"),
        ),
    )
    for i, wp in enumerate(track.get("path") or []):
        # Each waypoint: [time, lat, lon, baro_alt, true_track, on_ground]
        cursor.execute(
            """
            INSERT OR REPLACE INTO opensky_track_waypoints_data
                (track_request_params_json, waypoint_index, time,
                 latitude, longitude, baro_altitude, true_track, on_ground)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                params_json, i,
                wp[0] if len(wp) > 0 else None,
                wp[1] if len(wp) > 1 else None,
                wp[2] if len(wp) > 2 else None,
                wp[3] if len(wp) > 3 else None,
                wp[4] if len(wp) > 4 else None,
                1 if (len(wp) > 5 and wp[5]) else 0,
            ),
        )


def _load_track(cursor, params_json: str) -> dict | None:
    cursor.execute(
        "SELECT * FROM opensky_tracks_data WHERE request_params_json = ?",
        (params_json,),
    )
    track_row = cursor.fetchone()
    if not track_row:
        return None
    t_cols = [d[0] for d in cursor.description]
    track = dict(zip(t_cols, track_row))

    cursor.execute(
        "SELECT * FROM opensky_track_waypoints_data "
        "WHERE track_request_params_json = ? ORDER BY waypoint_index ASC",
        (params_json,),
    )
    wp_cols = [d[0] for d in cursor.description]
    track["path"] = [dict(zip(wp_cols, row)) for row in cursor.fetchall()]
    return track


# ---------------------------------------------------------------------------
# Generic cached-request wrapper
# ---------------------------------------------------------------------------

async def _cached_request(
    api_type: str,
    params_key: dict,
    fetch_fn,
    store_fn,
    load_fn,
    db_path: str,
) -> Any:
    """Generic cache-then-fetch pattern for OpenSky endpoints."""
    params_json = _cache_key(params_key)
    conn = setup_aircraft_db(db_path)
    cursor = conn.cursor()
    try:
        cached, api_ts = _is_cached(cursor, params_json, api_type)
        if cached:
            result = load_fn(cursor, params_json, api_ts) if api_ts is not None else load_fn(cursor, params_json)
            conn.close()
            return result

        raw = await fetch_fn()
        if raw is None:
            conn.close()
            return None

        conn.execute("BEGIN")
        _invalidate(cursor, params_json)
        api_ts = raw.get("time", int(time.time())) if isinstance(raw, dict) else int(time.time())
        _insert_request(cursor, params_json, api_type, api_ts)
        store_fn(cursor, params_json, raw)
        conn.commit()

        # Re-load from DB for a consistent return format
        conn.close()
        conn2 = setup_aircraft_db(db_path)
        c2 = conn2.cursor()
        result = load_fn(c2, params_json, api_ts) if api_ts is not None else load_fn(c2, params_json)
        conn2.close()
        return result

    except sqlite3.Error as exc:
        conn.rollback()
        conn.close()
        return f"Database error: {exc}"
    except Exception as exc:
        conn.close()
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:
    """Attach all OpenSky Network tools to *mcp*."""

    @mcp.tool(
        description=(
            "Retrieves live state vectors for all aircraft tracked by the OpenSky "
            "Network, optionally filtered by ICAO24 address(es) and/or a geographic "
            "bounding box. Results are cached for 1 hour. Returns a dict with 'time' "
            "and 'states' (list of state-vector dicts)."
        )
    )
    async def get_states(
        time_secs: int = 0,
        icao24: list[str] | str | None = None,
        lamin: float | None = None,
        lamax: float | None = None,
        lomin: float | None = None,
        lomax: float | None = None,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> dict | str | None:
        """
        Args:
            time_secs: Unix timestamp (0 = most recent).
            icao24:    One or more ICAO24 hex addresses to filter by.
            lamin:     Bounding-box minimum latitude.
            lamax:     Bounding-box maximum latitude.
            lomin:     Bounding-box minimum longitude.
            lomax:     Bounding-box maximum longitude.
            username:  OpenSky username (optional, enables higher rate limits).
            password:  OpenSky password.
            db_path:   SQLite database path.
        """
        icao_list = sorted([icao24] if isinstance(icao24, str) else (icao24 or []))
        has_bbox = all(v is not None for v in (lamin, lamax, lomin, lomax))
        api_params: dict[str, Any] = {"time": time_secs if time_secs else None}
        if icao_list:
            api_params["icao24"] = icao_list
        if has_bbox:
            api_params.update({"lamin": lamin, "lamax": lamax, "lomin": lomin, "lomax": lomax})

        cache_key_params = {"time": time_secs, "icao24": icao_list or None, "bbox": [lamin, lamax, lomin, lomax] if has_bbox else None}
        api_type = "states"

        async def fetch():
            return await _opensky_get("/states/all", api_params, username, password)

        def store(cursor, params_json, raw):
            _store_states(cursor, params_json, raw)

        def load(cursor, params_json, api_ts=0):
            return _load_states(cursor, params_json, api_ts)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves state vectors only from your own OpenSky sensors. "
            "Requires valid OpenSky Network credentials. Results are cached for 1 hour."
        )
    )
    async def get_my_states(
        time_secs: int = 0,
        icao24: list[str] | str | None = None,
        serials: list[int] | None = None,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> dict | str | None:
        """
        Args:
            time_secs: Unix timestamp (0 = most recent).
            icao24:    Filter by ICAO24 address(es).
            serials:   Filter by sensor serial number(s).
            username:  OpenSky username (required).
            password:  OpenSky password (required).
            db_path:   SQLite database path.
        """
        if not username or not password:
            return "Error: username and password are required for get_my_states."

        icao_list = sorted([icao24] if isinstance(icao24, str) else (icao24 or []))
        serial_list = sorted(serials) if serials else None
        api_params: dict[str, Any] = {"time": time_secs if time_secs else None}
        if icao_list:
            api_params["icao24"] = icao_list
        if serial_list:
            api_params["serials"] = serial_list

        cache_key_params = {"time": time_secs, "icao24": icao_list or None, "serials": serial_list, "_fn_": "my_states"}
        api_type = "my_states"

        async def fetch():
            return await _opensky_get("/states/own", api_params, username, password)

        def store(cursor, params_json, raw):
            _store_states(cursor, params_json, raw)

        def load(cursor, params_json, api_ts=0):
            return _load_states(cursor, params_json, api_ts)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves flights that arrived at the specified airport within a "
            "given time window. Results are cached for 1 hour."
        )
    )
    async def get_arrivals_by_airport(
        airport: str,
        begin: int,
        end: int,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> list | str | None:
        """
        Args:
            airport:  ICAO airport code (e.g. 'EDDF', 'VHHH', 'KLAX').
            begin:    Start of time window as Unix timestamp.
            end:      End of time window as Unix timestamp.
            username: OpenSky username (optional).
            password: OpenSky password.
            db_path:  SQLite database path.
        """
        cache_key_params = {"airport": airport, "begin": begin, "end": end, "_fn_": "arrivals"}
        api_type = "flights_arrivals"

        async def fetch():
            return await _opensky_get("/flights/arrival", {"airport": airport, "begin": begin, "end": end}, username, password)

        def store(cursor, params_json, raw):
            _store_flights(cursor, params_json, raw if isinstance(raw, list) else [])

        def load(cursor, params_json, api_ts=None):
            return _load_flights(cursor, params_json)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves flights that departed from the specified airport within a "
            "given time window. Results are cached for 1 hour."
        )
    )
    async def get_departures_by_airport(
        airport: str,
        begin: int,
        end: int,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> list | str | None:
        """
        Args:
            airport:  ICAO airport code (e.g. 'EDDF', 'VHHH', 'KLAX').
            begin:    Start of time window as Unix timestamp.
            end:      End of time window as Unix timestamp.
            username: OpenSky username (optional).
            password: OpenSky password.
            db_path:  SQLite database path.
        """
        cache_key_params = {"airport": airport, "begin": begin, "end": end, "_fn_": "departures"}
        api_type = "flights_departures"

        async def fetch():
            return await _opensky_get("/flights/departure", {"airport": airport, "begin": begin, "end": end}, username, password)

        def store(cursor, params_json, raw):
            _store_flights(cursor, params_json, raw if isinstance(raw, list) else [])

        def load(cursor, params_json, api_ts=None):
            return _load_flights(cursor, params_json)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves all flights performed by a specific aircraft (identified "
            "by its ICAO24 address) within a given time window. "
            "Results are cached for 1 hour."
        )
    )
    async def get_flights_by_aircraft(
        icao24: str,
        begin: int,
        end: int,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> list | str | None:
        """
        Args:
            icao24:   Aircraft ICAO24 hex address (e.g. 'abc9f3').
            begin:    Start of time window as Unix timestamp.
            end:      End of time window as Unix timestamp.
            username: OpenSky username (optional).
            password: OpenSky password.
            db_path:  SQLite database path.
        """
        cache_key_params = {"icao24": icao24, "begin": begin, "end": end, "_fn_": "by_aircraft"}
        api_type = "flights_by_aircraft"

        async def fetch():
            return await _opensky_get("/flights/aircraft", {"icao24": icao24, "begin": begin, "end": end}, username, password)

        def store(cursor, params_json, raw):
            _store_flights(cursor, params_json, raw if isinstance(raw, list) else [])

        def load(cursor, params_json, api_ts=None):
            return _load_flights(cursor, params_json)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves all flights tracked by OpenSky within a given time window "
            "(max 2-hour span). Results are cached for 1 hour."
        )
    )
    async def get_flights_from_interval(
        begin: int,
        end: int,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> list | str | None:
        """
        Args:
            begin:    Start of time window as Unix timestamp.
            end:      End of time window as Unix timestamp (max begin + 7200).
            username: OpenSky username (optional).
            password: OpenSky password.
            db_path:  SQLite database path.
        """
        cache_key_params = {"begin": begin, "end": end, "_fn_": "interval"}
        api_type = "flights_interval"

        async def fetch():
            return await _opensky_get("/flights/all", {"begin": begin, "end": end}, username, password)

        def store(cursor, params_json, raw):
            _store_flights(cursor, params_json, raw if isinstance(raw, list) else [])

        def load(cursor, params_json, api_ts=None):
            return _load_flights(cursor, params_json)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)

    @mcp.tool(
        description=(
            "Retrieves the trajectory / track (sequence of position waypoints) for "
            "a specific aircraft at a given time. If time is 0, returns the live "
            "track. Requires the aircraft to have been airborne within the last 30 "
            "days. Results are cached for 1 hour."
        )
    )
    async def get_track_by_aircraft(
        icao24: str,
        t: int = 0,
        username: str | None = None,
        password: str | None = None,
        db_path: str = "aircraft.db",
    ) -> dict | str | None:
        """
        Args:
            icao24:   Aircraft ICAO24 hex address (e.g. 'abc9f3').
            t:        Unix timestamp for the track (0 = current/live).
            username: OpenSky username (optional).
            password: OpenSky password.
            db_path:  SQLite database path.
        """
        cache_key_params = {"icao24": icao24, "time": t}
        api_type = "track"

        async def fetch():
            return await _opensky_get("/tracks/all", {"icao24": icao24, "time": t}, username, password)

        def store(cursor, params_json, raw):
            if isinstance(raw, dict):
                _store_track(cursor, params_json, raw)

        def load(cursor, params_json, api_ts=None):
            return _load_track(cursor, params_json)

        return await _cached_request(api_type, cache_key_params, fetch, store, load, db_path)
