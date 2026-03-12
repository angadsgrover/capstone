"""
Visibility Data Tools - Functions for fetching visibility data from HKO.

This module provides tools to retrieve visibility measurements from various
weather stations in Hong Kong from the Hong Kong Observatory API.
"""

from fastmcp import FastMCP
from typing import Dict
from ..service import HKClimateService

# Global climate service instance for tools
climate_service = HKClimateService()


def register(mcp: FastMCP):
    """Registers the visibility tool with the FastMCP server."""

    @mcp.tool(
        description="Get visibility data from various stations in Hong Kong from HKO.",
    )
    async def get_visibility_data(
        lang: str = "en"
    ) -> str:
        """
        Get visibility data from various stations in Hong Kong

        Args:
            lang: Language code ('en', 'tc', 'sc') for the response (default: 'en')

        Returns:
            JSON string containing visibility data
        """
        try:
            data = await climate_service.get_current_weather(lang)

            # Extract visibility data specifically
            visibility_data = data.get("visibility", {})

            result = {
                "visibility": visibility_data.get("data", []),
                "recordTime": visibility_data.get("recordTime", ""),
                "updateTime": data.get("updateTime", ""),
            }

            import json
            return json.dumps(result, indent=2)

        except Exception as e:
            import json
            return json.dumps({
                "error": "Failed to retrieve visibility data. The API endpoint may not be available.",
                "details": str(e)
            }, indent=2)