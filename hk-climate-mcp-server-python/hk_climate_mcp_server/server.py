"""
HK Climate MCP Server - A server for handling Hong Kong weather and climate data requests using the Model Context Protocol (MCP).

This module provides a server implementation for accessing Hong Kong weather data
through the MCP protocol. It supports both HTTP and stdio transports for communication.
"""

from fastmcp import FastMCP
from .tools import current_weather
from .tools import warnings
from .tools import visibility
from .tools import forecast


def server():
    """
    Create and configure the HK Climate MCP server.

    Returns:
        FastMCP: Configured MCP server instance with Hong Kong climate tools.
    """
    mcp = FastMCP(name="HKClimateServer")

    # Register all requested Hong Kong climate tools (excluding non-functional ones)
    for tool_register in [
        current_weather.register,
        warnings.register,
        visibility.register,
        forecast.register,
    ]:
        tool_register(mcp)

    return mcp