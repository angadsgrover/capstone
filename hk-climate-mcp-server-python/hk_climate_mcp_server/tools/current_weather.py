"""
Current Weather Data Tools - Functions for fetching current weather data from HKO.

This module provides tools to retrieve current weather information including temperature,
humidity, rainfall, and weather warnings from the Hong Kong Observatory API.
"""

from fastmcp import FastMCP
from typing import Dict
from ..service import HKClimateService

# Global climate service instance for tools
climate_service = HKClimateService()


def register(mcp: FastMCP):
    """Registers the current weather tool with the FastMCP server."""

    @mcp.tool(
        description="Get current weather data, warnings, temp, humidity in Hong Kong from HKO.",
    )
    async def get_current_weather(
        lang: str = "en"
    ) -> str:
        """
        Get current weather observations for Hong Kong

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')

        Returns:
            JSON string containing current weather data
        """
        try:
            data = await climate_service.get_current_weather(lang)

            # Format the response to include essential weather information
            result = {
                "generalSituation": data.get("generalSituation", "No general situation provided"),
                "warningMessages": data.get("warningMessage", []),
                "weatherObservation": {
                    "temperature": data.get("temperature", {}),
                    "humidity": data.get("humidity", {}),
                    "pressure": data.get("pressure", {}),
                    "visibility": data.get("visibility", {}),
                    "uvIndex": data.get("uvindex", {}),
                    "radiation": data.get("radiation", {})
                },
                "rainfall": data.get("rainfall", {}),
                "icon": data.get("icon", []),
                "updateTime": data.get("updateTime", ""),
            }

            import json
            return json.dumps(result, indent=2)

        except Exception as e:
            import json
            return json.dumps({
                "error": "Failed to retrieve current weather data. The API endpoint may not be available.",
                "details": str(e)
            }, indent=2)