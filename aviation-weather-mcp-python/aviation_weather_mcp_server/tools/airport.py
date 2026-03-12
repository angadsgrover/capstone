"""
Airport-related MCP tools for aviation weather data
"""

from fastmcp import FastMCP
from ..service import AviationWeatherService

weather_service = AviationWeatherService()

def register(mcp: FastMCP):
    """Register all airport tools with the FastMCP server."""
    _register_get_station_info(mcp)

def _register_get_station_info(mcp: FastMCP):
    @mcp.tool(
        description="Get detailed information about an airport or weather station",
    )
    async def get_station_info(
        station: str
    ) -> str:
        """
        Get detailed information about an airport or weather station.

        Args:
            station: ICAO airport/station code

        Returns:
            JSON string of station info
        """
        try:
            station_info = await weather_service.get_station_info(station)
            import json
            return json.dumps(station_info.__dict__, indent=2)
        except Exception as e:
            import json
            return json.dumps({"error": str(e), "data": {}})