"""Compatibility entrypoint for local ADS-B MCP startup.

This forwards to the packaged module entrypoint so imports resolve
consistently whether the server is launched via `python server.py` or
`python -m adsb_mcp_server`.
"""

from adsb_mcp_server.__main__ import main


if __name__ == "__main__":
    main()
