"""
Weather Warnings Tools - Functions for fetching weather warnings from HKO.

This module provides tools to retrieve current weather warnings and alerts
from the Hong Kong Observatory API.
"""

from fastmcp import FastMCP
from typing import Dict
from ..service import HKClimateService

# Global climate service instance for tools
climate_service = HKClimateService()


def register(mcp: FastMCP):
    """Registers the warnings tool with the FastMCP server."""

    @mcp.tool(
        description="Get current weather warnings in Hong Kong from HKO.",
    )
    async def get_weather_warnings(
        lang: str = "en"
    ) -> str:
        """
        Get current weather warnings in Hong Kong

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')

        Returns:
            JSON string containing weather warning data
        """
        try:
            data = await climate_service.get_warning_summary(lang)

            # Format the response to include essential warning information
            result = {
                "warnings": data,
                "updateTime": data.get("UpdateTime", "") if isinstance(data, dict) else "",
            }

            import json
            return json.dumps(result, indent=2)

        except Exception as e:
            import json
            return json.dumps({
                "error": "Failed to retrieve weather warnings. The API endpoint may not be available.",
                "details": str(e)
            }, indent=2)