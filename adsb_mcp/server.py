"""ADS-B MCP Server entry point.

Starts a FastMCP server exposing tools from three data sources:
  - adsb.lol API   : real-time aircraft tracking (tools/adsb.py)
  - FAA Registry   : aircraft registration lookup (tools/faa.py)
  - OpenSky Network: historical flight data with caching (tools/opensky.py)

Usage:
    python server.py               # stdio transport (default)
    python server.py --sse         # SSE transport on 127.0.0.1:8000
    python server.py --sse --port 9000 --host 0.0.0.0

Environment variables (overridden by CLI flags):
    TRANSPORT_MODE=sse
    HOST=0.0.0.0
    PORT=9000
"""

import argparse
import os

from fastmcp import FastMCP
from tools import adsb, faa, opensky


def create_server() -> FastMCP:
    """Instantiate and configure the FastMCP server with all tools."""
    mcp = FastMCP(name="AdsbMcpServer")

    for register_fn in [adsb.register, faa.register, opensky.register]:
        register_fn(mcp)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="ADS-B MCP Server")
    parser.add_argument(
        "-s", "--sse",
        action="store_true",
        help="Run in SSE mode instead of stdio",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    # Environment variables fill in defaults that were not set via CLI
    sse_mode = args.sse or os.environ.get("TRANSPORT_MODE") == "sse"

    host = args.host
    if host == parser.get_default("host"):
        host = os.environ.get("HOST", host)

    port = args.port
    if port == parser.get_default("port"):
        try:
            port = int(os.environ.get("PORT", port))
        except ValueError:
            pass

    mcp_server = create_server()
    if sse_mode:
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        mcp_server.run()


if __name__ == "__main__":
    main()
