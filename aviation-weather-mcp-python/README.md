# Aviation Weather MCP Server

A Model Context Protocol (MCP) server for aviation weather data, providing standardized access to METAR, TAF, PIREP, and AIRMET information for aviation applications.

## Features

- FastMCP-based server for aviation weather
- Tools for METAR, TAF, PIREP, AIRMET, and flight route weather

## Quick Start

### Requirements

- Python 3.10+
- [FastMCP](https://pypi.org/project/fastmcp/)
### Installation

```bash
pip install -e .
```

### Running the Server

#### CLI

```bash
aviation-weather-mcp          # Run with stdio transport (default)
aviation-weather-mcp --sse    # Run with SSE transport
aviation-weather-mcp --host 0.0.0 --port 8000  # Custom host/port
```

#### Python Module

```bash
python -m aviation_weather_mcp_server          # Run with stdio transport (default)
python -m aviation_weather_mcp_server --sse    # Run with SSE transport
```

#### Docker

```bash
docker build -t aviation-weather-mcp .
docker run --rm -it aviation-weather-mcp        # Run with stdio transport
```

## Tools

- **get_metar**: Fetch current METAR weather observations for airports
- **get_taf**: Fetch TAF (Terminal Aerodrome Forecast) for airports
- **get_pireps**: Fetch pilot reports (PIREPs) for a geographic area
- **get_airmets**: Fetch current AIRMETs (Airmen's Meteorological Information)
- **get_weather_along_route**: Get weather conditions along a flight route
- **get_weather_by_radius**: Get weather conditions within a radius of an airport

