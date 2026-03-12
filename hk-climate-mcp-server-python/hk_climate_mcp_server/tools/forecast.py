"""
Forecast Data Tools - Functions for fetching weather forecasts from HKO.

This module provides tools to retrieve weather forecasts from the Hong Kong 
Observatory API, including 7-day and 9-day forecasts.
"""

from fastmcp import FastMCP
from typing import Dict
from ..service import HKClimateService

# Global climate service instance for tools
climate_service = HKClimateService()


def register(mcp: FastMCP):
    """Registers the forecast tool with the FastMCP server."""

    @mcp.tool(
        description="Get weather forecast data for Hong Kong from HKO.",
    )
    async def get_weather_forecast(
        lang: str = "en",
        days: int = 7
    ) -> str:
        """
        Get weather forecast data for Hong Kong

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')
            days: Number of days for forecast (7 or 9) (default: 7)

        Returns:
            JSON string containing forecast data
        """
        try:
            if days == 9:
                data = await climate_service.get_forecast_9day(lang)
            else:
                data = await climate_service.get_forecast_7day(lang)

            result = {
                "forecastData": data,
                "days": days,
                "updateTime": data.get("UpdateTime", "") if isinstance(data, dict) else "",
            }

            import json
            return json.dumps(result, indent=2)

        except Exception as e:
            import json
            return json.dumps({
                "error": "Failed to retrieve forecast data. The API endpoint may not be available.",
                "details": str(e)
            }, indent=2)