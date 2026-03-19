# ADS-B MCP Server

MCP server for aircraft tracking, FAA registry lookups, and OpenSky historical flight data.

Used by the `agent` service for `aircraft` and `general` routes.

## Features

- FastMCP server with stdio and SSE transports
- adsb.lol real-time tracking tools
- FAA registry scraping tools
- OpenSky API wrappers with local caching
- SQLite persistence (`aircraft.db`) for repeat queries and offline analysis

## Tool Groups

ADSB.lol examples:

- `get_callsign`, `get_registration`, `get_squawk`, `get_icao_hex`, `get_type`
- `get_search_radius`
- `get_arrivals_by_airport`, `get_departures_by_airport`
- `get_pia`, `get_mil`, `get_ladd`

FAA examples:

- `batch_lookup_faa`
- `create_or_update_faa`
- `get_faa_entry`
- `delete_faa_entry`

OpenSky examples:

- `get_states`, `get_my_states`
- `get_arrivals_by_airport`, `get_departures_by_airport`
- `get_flights_by_aircraft`, `get_flights_from_interval`
- `get_track_by_aircraft`

## Installation

From `adsb_mcp`:

```bash
pip install -e .
```

## Run

```bash
python server.py
python server.py --sse
python server.py --sse --host 0.0.0.0 --port 9000
```

Environment defaults (overridden by CLI):

- `TRANSPORT_MODE=sse`
- `HOST=0.0.0.0`
- `PORT=9000`

## Integration

Connected via MCP config in the `agent` service.
Local DB caching/persistence helps reduce upstream API pressure and improves repeat-query latency.
