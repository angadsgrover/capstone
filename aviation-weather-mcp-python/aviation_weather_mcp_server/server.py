from fastmcp import FastMCP
from .tools import weather
from .tools import flight_route
from .tools import analysis
from .tools import airport
from .tools import prompts


def server():
    """
    Create and configure the Aviation Weather MCP server.

    Returns:
        FastMCP: Configured MCP server instance with aviation weather tools.
    """
    mcp = FastMCP(name="AviationWeatherServer")

    # Register all aviation weather tools in a clear, extensible way
    for tool_register in [
        weather.register,
        flight_route.register,
        analysis.register,
        airport.register,
        prompts.register,
    ]:
        tool_register(mcp)

    return mcp