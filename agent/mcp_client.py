from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional
import asyncio
import logging
import shutil
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.types import Tool as MCPTool
from langchain_core.tools import StructuredTool

logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Tool outputs > this many chars are truncated before being stored in LLM context.
# Keeps individual tool results to ~2 k tokens; avoids blowing the context window
# on large ADS-B radius searches or verbose weather dumps.
MAX_TOOL_OUTPUT_CHARS = 8_000


def _json_type_to_python(json_type: str) -> type:
    """Map JSON Schema type strings to Python types."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, str)


class MCPClient:
    """Manages connections to one or more MCP servers based on mcp_config.json.

    Supports both transports:
    • stdio  — config has ``command`` + ``args`` (subprocess)
    • SSE    — config has ``url``  (HTTP Server-Sent Events)
    """

    def __init__(self) -> None:
        self.servers: List["MCPServer"] = []
        self.config: dict[str, Any] = {}
        self.tools: List[Any] = []
        self.exit_stack = AsyncExitStack()

    def load_servers(self, config_path: str) -> None:
        with open(config_path, "r") as config_file:
            self.config = json.load(config_file)
        self.servers = [
            MCPServer(name, cfg)
            for name, cfg in self.config["mcpServers"].items()
        ]

    async def start_langchain(self) -> Dict[str, List[StructuredTool]]:
        """Start each MCP server and return tools grouped by server name."""
        tools_by_server: Dict[str, List[StructuredTool]] = {}
        for server in self.servers:
            try:
                await server.initialize()
                tools = await server.create_langchain_tools()
                tools_by_server[server.name] = tools
            except Exception as e:
                logging.error(f"Failed to initialise server {server.name}: {e}")
                await self.cleanup_servers()
                return {}
        return tools_by_server

    async def cleanup_servers(self) -> None:
        for server in self.servers:
            try:
                await server.cleanup()
            except Exception as e:
                logging.warning(f"Warning during cleanup of server {server.name}: {e}")

    async def cleanup(self) -> None:
        try:
            await self.cleanup_servers()
        except Exception as e:
            logging.warning(f"Warning during server cleanup: {e}")
        finally:
            try:
                await self.exit_stack.aclose()
            except Exception as e:
                logging.warning(f"Warning during exit stack cleanup: {e}")


class MCPServer:
    """Manages a single MCP server connection (stdio or SSE)."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config
        self._use_sse: bool = "url" in config
        self.session: Optional[ClientSession] = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()

    async def initialize(self) -> None:
        """Open the server connection (SSE or stdio)."""
        if self._use_sse:
            await self._initialize_sse()
        else:
            await self._initialize_stdio()

    async def _initialize_sse(self) -> None:
        url = self.config["url"]
        logging.info(f"Connecting to MCP server {self.name} via SSE: {url}")
        try:
            sse_transport = await self.exit_stack.enter_async_context(
                sse_client(url)
            )
            read, write = sse_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self.session = session
        except Exception as e:
            logging.error(f"Error connecting to SSE server {self.name} at {url}: {e}")
            await self.cleanup()
            raise

    async def _initialize_stdio(self) -> None:
        cfg_command = self.config.get("command")
        if not cfg_command:
            raise ValueError(
                f"Server {self.name}: config must include 'command' (stdio) or 'url' (SSE)."
            )
        resolved = shutil.which(cfg_command)
        command = resolved if resolved is not None else cfg_command

        server_params = StdioServerParameters(
            command=command,
            args=self.config.get("args", []),
            env=self.config.get("env") or {},
        )
        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self.session = session
        except Exception as e:
            logging.error(f"Error initialising stdio server {self.name}: {e}")
            await self.cleanup()
            raise

    async def create_langchain_tools(self) -> List[StructuredTool]:
        """Convert every MCP tool exposed by this server into a LangChain StructuredTool."""
        tools = (await self.session.list_tools()).tools
        return [self._create_langchain_tool(t) for t in tools]

    def _create_langchain_tool(self, tool: MCPTool) -> StructuredTool:
        session = self.session

        async def _invoke(**kwargs: Any) -> str:
            result = await session.call_tool(tool.name, arguments=kwargs)
            # Extract text from MCP CallToolResult
            if hasattr(result, "content"):
                parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
                output = "\n".join(parts) if parts else str(result)
            else:
                output = str(result)

            # Truncate to keep LLM context manageable
            if len(output) > MAX_TOOL_OUTPUT_CHARS:
                output = (
                    output[:MAX_TOOL_OUTPUT_CHARS]
                    + f"\n\n[...output truncated at {MAX_TOOL_OUTPUT_CHARS} chars"
                    f" — {len(output) - MAX_TOOL_OUTPUT_CHARS} chars omitted...]"
                )
            return output

        # Build Pydantic args schema from the MCP tool's JSON Schema
        from pydantic import create_model, Field
        from typing import Optional as Opt

        schema = tool.inputSchema or {"type": "object", "properties": {}}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields: dict = {}
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type")

            if not prop_type and "anyOf" in prop_schema:
                for option in prop_schema["anyOf"]:
                    if option.get("type") and option.get("type") != "null":
                        prop_type = option.get("type")
                        break

            if isinstance(prop_type, list):
                types = [t for t in prop_type if t != "null"]
                prop_type = types[0] if types else "string"

            field_type = _json_type_to_python(prop_type or "string")
            default = ... if prop_name in required else prop_schema.get("default", None)

            if prop_name not in required and default is None:
                field_type = Opt[field_type]

            fields[prop_name] = (
                field_type,
                Field(default=default, description=prop_schema.get("description", "")),
            )

        args_model = create_model(f"{tool.name}_args", **fields) if fields else None

        return StructuredTool(
            name=tool.name,
            description=tool.description or tool.name,
            coroutine=_invoke,
            func=lambda **kw: None,  # sync stub — always use coroutine path
            args_schema=args_model,
        )

    async def cleanup(self) -> None:
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
            except Exception as e:
                logging.error(f"Error closing exit stack for server {self.name}: {e}")
            finally:
                self.session = None
