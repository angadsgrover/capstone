from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional
import asyncio
import contextvars
import logging
import shutil
import json
import os
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.types import Tool as MCPTool
from langchain_core.tools import StructuredTool

try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree
except Exception:  # pragma: no cover - safe no-op fallback when langsmith unavailable
    def traceable(*args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def _decorator(fn):
            return fn

        return _decorator

    def get_current_run_tree():
        return None

logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Tool outputs > this many chars are truncated before being stored in LLM context.
# Keeps individual tool results to ~2 k tokens; avoids blowing the context window
# on large ADS-B radius searches or verbose weather dumps.
MAX_TOOL_OUTPUT_CHARS = 8_000

# Tool-call governance to prevent fan-out storms and duplicate work.
# These limits are per-REQUEST, not per-step. For planning mode with multiple
# airports, we need higher limits since each step may query different airports.
MAX_TOOL_CALLS_PER_REQUEST = int(os.getenv("MCP_MAX_TOOL_CALLS_PER_REQUEST", "80"))
TOOL_CACHE_TTL_SECONDS = int(os.getenv("MCP_TOOL_CACHE_TTL_SECONDS", "300"))

# Identical parameter calls (exact same tool + same args) are blocked after this count
MAX_IDENTICAL_CALLS_PER_REQUEST = int(os.getenv("MCP_MAX_IDENTICAL_CALLS_PER_REQUEST", "1"))

# Per-tool-name limits. These apply to the SAME tool with DIFFERENT parameters.
# For multi-airport queries, we need higher limits.
MAX_TOOL_NAME_CALLS_PER_REQUEST = int(os.getenv("MCP_MAX_TOOL_NAME_CALLS_PER_REQUEST", "15"))

# Tools that commonly need multiple calls with different parameters
MULTI_CALL_TOOLS = frozenset({
    "lookup_airport_codes",
    "get_metar",           # multiple airports in planning
    "get_taf",             # multiple airports in planning
    "get_arrivals_by_airport",
    "get_departures_by_airport",
    "get_states",          # different bounding boxes
    "get_search_radius",   # different coordinates
    "get_pireps",          # different regions
})
MAX_MULTI_CALL_TOOL_REQUESTS = int(os.getenv("MCP_MAX_MULTI_CALL_TOOL_REQUESTS", "8"))

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_request_id", default="")
_cache_lock = asyncio.Lock()
_tool_cache: Dict[str, tuple[float, str]] = {}
_request_call_counts: Dict[str, int] = {}
_request_cache: Dict[str, Dict[str, str]] = {}
_request_inflight: Dict[tuple[str, str], asyncio.Future] = {}
_request_key_counts: Dict[str, Dict[str, int]] = {}
_request_tool_counts: Dict[str, Dict[str, int]] = {}


def set_request_context(request_id: str) -> None:
    """Bind MCP tool execution to a request scope for dedup/rate-limiting."""
    _request_id_var.set(request_id or "")


def clear_request_context(request_id: Optional[str] = None) -> None:
    """Clear request-scoped MCP tracking data to avoid unbounded growth."""
    rid = request_id or _request_id_var.get()
    _request_id_var.set("")
    if not rid:
        return

    _request_call_counts.pop(rid, None)
    _request_cache.pop(rid, None)
    _request_key_counts.pop(rid, None)
    _request_tool_counts.pop(rid, None)

    to_remove = [key for key in _request_inflight if key[0] == rid]
    for key in to_remove:
        fut = _request_inflight.pop(key, None)
        if fut and not fut.done():
            fut.cancel()


def _cache_key(tool_name: str, kwargs: Dict[str, Any]) -> str:
    payload = json.dumps(kwargs, sort_keys=True, separators=(",", ":"), default=str)
    return f"{tool_name}:{payload}"


def _current_session_id() -> str:
    request_id = _request_id_var.get()
    if not request_id:
        return ""
    return request_id.split(":", 1)[0].strip()


def _annotate_tool_span(tool_name: str) -> None:
    run_tree = get_current_run_tree()
    if not run_tree:
        return

    try:
        metadata = dict(getattr(run_tree, "metadata", {}) or {})
        session_id = _current_session_id()
        if session_id:
            metadata["session_id"] = session_id
            metadata["thread_id"] = session_id
            metadata["conversation_id"] = session_id
        metadata["tool_name"] = tool_name
        run_tree.metadata = metadata
    except Exception:
        return


def _normalize_kwargs(tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize semantically equivalent MCP tool arguments for better dedup hits."""
    normalized = {k: v for k, v in kwargs.items() if v is not None}

    # Canonicalize common scalar/list forms so semantically identical calls
    # share the same cache key.
    int_fields = {"hours", "hours_back", "limit", "max_results"}
    float_fields = {"lat", "lon", "radius", "radius_nm"}
    uppercase_fields = {
        "icao",
        "iata",
        "station",
        "stations",
        "airport",
        "airport_code",
        "departure_airport",
        "arrival_airport",
    }

    def _norm_scalar(field: str, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if field == "lang":
                return text.lower()

            if field in int_fields:
                try:
                    return int(text)
                except Exception:
                    return text

            if field in float_fields:
                try:
                    return float(text)
                except Exception:
                    return text

            if field in uppercase_fields:
                # Handle comma-separated station lists such as "vhhh, egll".
                if "," in text:
                    parts = [p.strip().upper() for p in text.split(",") if p.strip()]
                    if parts:
                        return ",".join(parts)
                return text.upper()

            return text

        if isinstance(value, (int, float, bool)):
            return value

        return value

    for field, value in list(normalized.items()):
        if isinstance(value, list):
            normalized[field] = [_norm_scalar(field, v) for v in value]
        else:
            normalized[field] = _norm_scalar(field, value)

    if tool_name in {
        "get_current_weather",
        "get_weather_warnings",
        "get_visibility_data",
        "get_weather_forecast",
    } and "lang" not in normalized:
        normalized["lang"] = "en"

    return normalized


def _purge_expired_tool_cache() -> None:
    if not _tool_cache:
        return
    now = time.time()
    expired = [key for key, (expires_at, _) in _tool_cache.items() if expires_at <= now]
    for key in expired:
        _tool_cache.pop(key, None)


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
            _annotate_tool_span(tool.name)
            norm_kwargs = _normalize_kwargs(tool.name, kwargs)
            key = _cache_key(tool.name, norm_kwargs)
            request_id = _request_id_var.get()
            inflight_key = (request_id, key)

            wait_for: Optional[asyncio.Future] = None
            own_call = False

            async with _cache_lock:
                _purge_expired_tool_cache()

                cached = _tool_cache.get(key)
                if cached and cached[0] > time.time():
                    return cached[1]

                if request_id:
                    request_cached = _request_cache.setdefault(request_id, {})
                    key_counts = _request_key_counts.setdefault(request_id, {})
                    key_count = key_counts.get(key, 0)

                    # Determine limit based on tool type
                    tool_limit = (
                        MAX_MULTI_CALL_TOOL_REQUESTS
                        if tool.name in MULTI_CALL_TOOLS
                        else MAX_TOOL_NAME_CALLS_PER_REQUEST
                    )

                    tool_counts = _request_tool_counts.setdefault(request_id, {})
                    tool_count = tool_counts.get(tool.name, 0)
                    if tool_count >= tool_limit:
                        logging.warning(f"Tool limit hit: {tool.name} called {tool_count} times")
                        return (
                            f"[LIMIT] Tool '{tool.name}' has been called {tool_limit} times already. "
                            f"Use the data you already have and proceed with your analysis."
                        )

                    # Strong duplicate guard: once a key has been called successfully or not,
                    # don't allow identical retries in the same request.
                    if key_count >= MAX_IDENTICAL_CALLS_PER_REQUEST:
                        logging.debug(f"Duplicate call hard-blocked: {tool.name} with same params")
                        return (
                            f"[DUPLICATE_BLOCKED] '{tool.name}' was already called with these exact "
                            "parameters in this request. Do not call it again. "
                            "Synthesize a final answer from available results and explicitly note any "
                            "missing live data."
                        )

                    # If the same call already completed and is cached in-request, reuse it.
                    if key in request_cached:
                        return request_cached[key]

                    existing = _request_inflight.get(inflight_key)
                    if existing is not None:
                        wait_for = existing
                    else:
                        count = _request_call_counts.get(request_id, 0)
                        if count >= MAX_TOOL_CALLS_PER_REQUEST:
                            logging.warning(f"Total tool call limit hit: {count} calls")
                            return (
                                f"[LIMIT] Maximum tool calls ({MAX_TOOL_CALLS_PER_REQUEST}) reached. "
                                f"Synthesize your answer using the data already gathered."
                            )
                        _request_call_counts[request_id] = count + 1
                        tool_counts[tool.name] = tool_count + 1
                        key_counts[key] = key_count + 1
                        loop = asyncio.get_running_loop()
                        _request_inflight[inflight_key] = loop.create_future()
                        own_call = True
                else:
                    own_call = True

            if wait_for is not None:
                return await wait_for

            if not own_call:
                # Edge case: request context dedup hit but no inflight/cache
                # This shouldn't happen normally, but return helpful message
                return f"[Tool {tool.name} skipped - already queried with same parameters]"

            try:
                result = await session.call_tool(tool.name, arguments=norm_kwargs)
            except Exception as exc:
                logging.error(f"Tool {tool.name} failed: {exc}")
                if request_id:
                    async with _cache_lock:
                        fut = _request_inflight.pop(inflight_key, None)
                        if fut and not fut.done():
                            fut.set_exception(exc)
                raise
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

            # Some MCP tools encode missing data as JSON null / empty strings.
            # Replace with explicit guidance so the agent doesn't keep retrying.
            stripped_output = output.strip()
            is_no_data = stripped_output.lower() in {"", "null", "none"}
            if not is_no_data and stripped_output:
                try:
                    is_no_data = json.loads(stripped_output) is None
                except Exception:
                    is_no_data = False

            if is_no_data:
                args_text = json.dumps(norm_kwargs, sort_keys=True, default=str)
                output = (
                    f"[NO_DATA] Tool '{tool.name}' returned no data for arguments {args_text}. "
                    "Do not call this tool again with the same parameters in this request. "
                    "Provide a best-effort answer and clearly state that live data is currently unavailable."
                )

            async with _cache_lock:
                _tool_cache[key] = (time.time() + TOOL_CACHE_TTL_SECONDS, output)
                if request_id:
                    _request_cache.setdefault(request_id, {})[key] = output
                    fut = _request_inflight.pop(inflight_key, None)
                    if fut and not fut.done():
                        fut.set_result(output)

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

        traced_invoke = traceable(
            name=f"mcp.{tool.name}",
            run_type="tool",
        )(_invoke)

        return StructuredTool(
            name=tool.name,
            description=tool.description or tool.name,
            coroutine=traced_invoke,
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
