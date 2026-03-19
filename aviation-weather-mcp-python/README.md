# Aviation Weather MCP Server

MCP server exposing aviation weather tools for METAR, TAF, PIREP, AIRMET, and route-level weather checks.

Used by the `agent` service for `aviation_weather` and `general` routes.

## Features

- FastMCP-based tool server
- Supports stdio and SSE transports
- Airport, radius, and route weather utility tools
- Flight category and VFR checks for pilot workflows

## Toolset

- `get_metar`
- `get_taf`
- `get_pireps`
- `get_airmets`
- `get_weather_along_route`
- `get_weather_by_radius`
- `determine_flight_category`
- `check_vfr_minimums`

## Installation

From `aviation-weather-mcp-python`:

```bash
pip install -e .
```

## Run

CLI:

```bash
aviation-weather-mcp
aviation-weather-mcp --sse
aviation-weather-mcp --sse --host 0.0.0.0 --port 8000
```

Module mode:

```bash
python -m aviation_weather_mcp_server
python -m aviation_weather_mcp_server --sse
```

## Integration

The `agent` service connects through its MCP config (`agent/mcp_config.json` and `agent/mcp_config.docker.json`).
Keep tool names and signatures stable to avoid downstream orchestrator breakage.
