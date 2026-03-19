# HK Climate MCP Server

MCP server exposing Hong Kong Observatory (HKO) weather endpoints for current conditions, warnings, visibility, and forecast data.

Used by the `agent` service for `hk_weather` and `general` routes.

## Features

- FastMCP server with stdio and SSE transports
- Async service layer with timeout/error handling
- JSON-formatted tool outputs for predictable parsing

## Toolset

- `get_current_weather`
- `get_weather_warnings`
- `get_visibility_data`
- `get_weather_forecast` (7-day or 9-day)

## Installation

From `hk-climate-mcp-server-python`:

```bash
pip install -e .
```

## Run

CLI:

```bash
hk-climate-mcp
hk-climate-mcp --sse
hk-climate-mcp --sse --host 0.0.0.0 --port 8000
```

Module mode:

```bash
python -m hk_climate_mcp_server
python -m hk_climate_mcp_server --sse
```

## Integration

This server is connected via MCP config in the `agent` service.
Tool responses are consumed as structured JSON strings by specialist prompts.
