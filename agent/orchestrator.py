"""
LangGraph multi-step agent orchestrator with specialist sub-agents.

Architecture:
  User Input
      │
      ▼
  router  ──classifies intent──►  aviation_weather │ hk_weather │ aircraft │ general │ planning
                                       │
                                  create_agent (ReAct loop with focused tools)
                                       │
                                      END

Advanced Features:
  - **Planning Mode**: Complex multi-step queries are auto-detected and routed to plan-and-execute
  - **Self-Healing**: Tool failures trigger LLM-based parameter correction + retry

Context management:
  Each specialist receives at most MAX_HISTORY_MESSAGES recent messages so the
  LLM's context window stays within budget across long conversations.
  Full history is still persisted by MemorySaver for the checkpointer.

Conversation memory: MemorySaver checkpointer keyed by session_id / thread_id.
"""
import asyncio
import csv
import json
import logging
import os
import pathlib
from typing import Annotated, Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain.agents import create_agent

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

import mcp_client as mcp_module

# Optional imports for advanced features
try:
    from planning import should_use_planning, build_plan_execute_graph
    PLANNING_AVAILABLE = True
except ImportError:
    PLANNING_AVAILABLE = False

try:
    from advanced_tools import execute_with_healing, ToolComposer, wrap_tools_with_healing
    HEALING_AVAILABLE = True
except ImportError:
    HEALING_AVAILABLE = False

SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
_mcp_cfg_env = os.environ.get("MCP_CONFIG")
CONFIG_FILE = pathlib.Path(_mcp_cfg_env) if _mcp_cfg_env else SCRIPT_DIR / "mcp_config.json"
ICAO_MAPPING_FILE = SCRIPT_DIR / "icao_mapping.csv"

load_dotenv()
logger = logging.getLogger(__name__)

# ── Context-length tuning ─────────────────────────────────────────────────────

# Maximum number of messages passed to each specialist LLM per call.
# Older messages are silently dropped from the *inference* window; the full
# history is still stored in the MemorySaver checkpointer.
MAX_HISTORY_MESSAGES = 20

# Maximum tokens a specialist may generate in a single response.
MAX_RESPONSE_TOKENS = 2_048


# ── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    route: str          # set by router node, read by conditional edge
    planning_data: Dict[str, Any]


# ── LLM factory ───────────────────────────────────────────────────────────────

def get_chat_model(streaming: bool = True, max_tokens: int = MAX_RESPONSE_TOKENS) -> ChatOpenAI:
    """Return a ChatOpenAI instance pointed at OpenRouter."""
    return ChatOpenAI(
        model=os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini"),
        base_url=os.getenv("BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
        streaming=streaming,
        temperature=0,
        max_tokens=max_tokens,
        default_headers={"HTTP-Referer": "http://localhost:5173"},
    )


# ── Local airport-lookup tool ─────────────────────────────────────────────────

def _search_airport(location: str, max_results: int = 10) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    loc_lower = location.lower().strip()
    try:
        with open(ICAO_MAPPING_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("icao"):
                    continue
                if (
                    loc_lower in row.get("icao", "").lower()
                    or loc_lower in row.get("airport", "").lower()
                    or loc_lower in row.get("region_name", "").lower()
                    or loc_lower in row.get("country_code", "").lower()
                    or loc_lower in row.get("iata", "").lower()
                ):
                    results.append({
                        "icao": row["icao"],
                        "iata": row.get("iata", ""),
                        "airport": row.get("airport", ""),
                        "region": row.get("region_name", ""),
                        "country": row.get("country_code", ""),
                    })
                if len(results) >= max_results:
                    break
    except Exception as e:
        return [{"error": str(e)}]
    return results or [{"error": f"No airport matching: {location}"}]


@tool
def lookup_airport_codes(location: str, max_results: int = 10) -> str:
    """
    Find airport ICAO codes by location name, airport name, city, country, or IATA code.
    ALWAYS call this first when the user mentions a place name without an ICAO code.

    Examples:
      lookup_airport_codes("Heathrow")   → [{icao: "EGLL", ...}]
      lookup_airport_codes("Hong Kong")  → [{icao: "VHHH", ...}]
      lookup_airport_codes("London")     → EGLL, EGLC, EGKK, EGSS, ...
      lookup_airport_codes("JFK")        → [{icao: "KJFK", ...}]
    """
    return json.dumps(_search_airport(location, max_results), indent=2)


# ── Environment ──────────────────────────────────────────────────────────────

ENABLE_PLANNING = os.getenv("ENABLE_PLANNING", "true").lower() == "true"
ENABLE_SELF_HEALING = os.getenv("ENABLE_SELF_HEALING", "true").lower() == "true"
PLANNING_RECURSION_LIMIT = int(os.getenv("PLANNING_RECURSION_LIMIT", "80"))


def _resolve_llm_config(runtime_config: RunnableConfig) -> Dict[str, str]:
    """Resolve LLM config with env fallback for planner and healing flows."""
    if not isinstance(runtime_config, dict):
        runtime_config = {}

    raw_configurable = runtime_config.get("configurable", {})
    configurable = raw_configurable if isinstance(raw_configurable, dict) else {}
    session_id = configurable.get("thread_id") or configurable.get("session_id") or ""
    return {
        "model": configurable.get("model") or os.getenv("MODEL_CHOICE", "openai/gpt-4o-mini"),
        "base_url": configurable.get("base_url") or os.getenv("BASE_URL", "https://openrouter.ai/api/v1"),
        "api_key": configurable.get("api_key") or os.getenv("LLM_API_KEY", ""),
        "session_id": session_id,
    }


def _annotate_thread_metadata(config: RunnableConfig) -> None:
    if not isinstance(config, dict):
        return
    configurable = config.get("configurable", {})
    if not isinstance(configurable, dict):
        return
    thread_id = str(configurable.get("thread_id") or configurable.get("session_id") or "").strip()
    if not thread_id:
        return

    run_tree = get_current_run_tree()
    if not run_tree:
        return

    try:
        metadata = dict(getattr(run_tree, "metadata", {}) or {})
        metadata["session_id"] = thread_id
        metadata["thread_id"] = thread_id
        metadata["conversation_id"] = thread_id
        run_tree.metadata = metadata
    except Exception:
        return

# ── System prompts ────────────────────────────────────────────────────────────

ROUTER_PROMPT = """\
You are a strict query router for an aviation intelligence system.

Task:
Classify the user query into EXACTLY ONE category:

aviation_weather — METAR, TAF, PIREPs, AIRMETs, VFR/IFR conditions, route weather, airport weather briefings
hk_weather       — Hong Kong weather, HKO forecasts, HK typhoon/rainstorm warnings, HK visibility
aircraft         — live flight tracking, ADS-B positions, callsign/registration lookup, flight history, arrivals/departures
planning         — complex queries requiring multiple steps, comparisons between airports, or sequential operations
general          — mixed queries, comparisons across multiple domains, or anything that doesn't fit above

Routing rules:
- Use planning when the user asks for comparisons, trade-offs, ranking, or sequential analysis.
- Compare multiple airports or locations
- Ask for sequential analysis (first X, then Y)
- Require combining data from multiple sources
- Use words like "compare", "both", "versus", "best", "optimal"
- Prefer aviation_weather over hk_weather when the query is airport/flight-weather specific (e.g., METAR/TAF/flight category).
- Prefer aircraft when the query is about live traffic, callsigns, registrations, or flight movement.
- Use general only when none of the above clearly apply.

Output format:
- Reply with ONLY one token: aviation_weather | hk_weather | aircraft | planning | general
- No explanation, no punctuation, no extra words."""

AVIATION_PROMPT = """\
You are an aviation weather specialist.

Goal:
Provide a clear, operationally useful briefing for pilots and dispatch users.

Hard rules:
- Do not invent weather observations or forecasts.
- If required data is missing/unavailable, say so explicitly and provide a safe fallback recommendation.
- Keep statements tied to tool outputs and timestamps.

**Workflow:**
1. **Resolve location** → If user gives a city/airport name (not ICAO), call `lookup_airport_codes` first
2. **Check context** → Use `rag_search` for historical patterns, trends, or safety notes
3. **Get current data** → Select appropriate tools:
   - Airport: `get_metar`, `get_taf`
   - Route: `get_weather_along_route`, `determine_flight_category`
   - Area: `get_pireps`, `get_airmets`
4. **Synthesize** → Clear briefing with:
   - Current conditions + flight category (VFR/MVFR/IFR/LIFR)
   - Key hazards or NOTAMs
   - Historical context if relevant
   - Recommendations

**Format:**
- Start with executive summary (1-2 sentences)
- Use headers: ## Current Conditions, ## Forecast, ## Recommendations
- Include data sources and timestamps; if stale/unknown, label it
- Highlight critical weather (bold or ⚠️)"""

HK_PROMPT = """\
You are a Hong Kong weather specialist with HKO data expertise.

**Important:** HKO tools provide civic weather, NOT aviation METAR/TAF.
For airport weather, redirect to aviation specialist.

Hard rules:
- Do not fabricate warning signals, forecast values, or observation times.
- If HKO data is unavailable, clearly state the gap and provide a conservative summary.

**Workflow:**
1. **Historical context** → `rag_search` for past HK weather patterns
2. **Current conditions** → `get_current_weather`
3. **Active warnings** → `get_weather_warnings` (typhoons, rainstorms)
4. **Forecast** → `get_weather_forecast`
5. **Visibility** (if needed) → `get_visibility_data`

**Format:**
- Summary: Current conditions + active warnings
- ## Current Weather (temp, humidity, wind)
- ## Active Warnings (typhoon signals, rainstorm warnings)
- ## Forecast (next 24-48 hours)
- ## Historical Context (if relevant patterns found)
- Include source timestamps when available"""

AIRCRAFT_PROMPT = """\
You are an ADS-B tracking specialist. Provide real-time flight information.

Hard rules:
- Do not infer precise positions/routes if data is absent.
- Distinguish confirmed telemetry from assumptions.
- If no flights are found, say that explicitly and suggest a narrower query.

**Workflow:**
1. **Resolve airports** → Use `lookup_airport_codes` for place names
2. **Track flights:**
   - By callsign → `get_callsign`
   - By registration → `get_registration`
   - By area → `get_search_radius` (lat, lon, radius_nm)
   - Arrivals → `get_arrivals_by_airport`
   - Departures → `get_departures_by_airport`
   - History → `get_flights_by_aircraft` (needs ICAO24 hex)
   - Emergency → `get_squawk` (7700=emer, 7600=radio, 7500=hijack)

**Format:**
- Summary: Number of flights found, key details
- ## Flight Details (callsign, position, altitude, speed, track)
- ## Route (origin → destination if known)
- Present as table for multiple flights with last-seen timing when available"""

GENERAL_PROMPT = """\
You are a comprehensive aviation & weather assistant with access to all tools.

Goal:
Answer mixed-domain user requests accurately while selecting the right specialist tools.

Hard rules:
- Do not fabricate tool outputs.
- Ask tools for evidence before making factual claims.
- If information is uncertain or unavailable, explicitly mark uncertainty.

**Available Tools:**
- **Location** → `lookup_airport_codes` (always call first for place names)
- **Historical** → `rag_search` (past weather, safety data, benchmarks)
- **Aviation** → `get_metar`, `get_taf`, PIREPs, AIRMETs, flight categories
- **HK Weather** → HKO current/forecast/warnings
- **Tracking** → ADS-B live/history

**Workflow:**
1. Resolve locations to ICAO codes
2. Search historical context with `rag_search`
3. Call relevant data tools (avoid mixing HKO and METAR for same query)
4. Synthesize comprehensive response

**Important:**
- For METAR/TAF requests → use aviation tools (`get_metar`/`get_taf`)
- For HK civic weather → use HKO tools (`get_current_weather`)
- Don't call both for the same location unless explicitly requested

**Format:**
- Clear summary upfront
- Organize response with headers
- Cite data sources and timestamps; call out stale/missing data
- Include recommendations if actionable"""


# Maximum ReAct steps (agent↔tools rounds) per specialist call.
# Default LangGraph limit is 25; complex multi-tool queries need more headroom.
SPECIALIST_RECURSION_LIMIT = 50


# ── Context trimming ──────────────────────────────────────────────────────────

def _trim_messages(messages: list, max_count: int = MAX_HISTORY_MESSAGES) -> list:
    """Return the most recent `max_count` messages.

    Preserves the full state in the checkpointer; only limits what the LLM sees
    on each inference call.  The slice always starts at a natural boundary so
    the specialist sees a coherent conversation snippet.
    """
    if len(messages) <= max_count:
        return messages
    return messages[-max_count:]


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_graph(
    aviation_tools: List[StructuredTool],
    hk_tools: List[StructuredTool],
    adsb_tools: List[StructuredTool],
    checkpointer: MemorySaver,
    memory_manager=None,
    db=None,
):
    llm = get_chat_model(streaming=True)
    router_llm = get_chat_model(streaming=False, max_tokens=16)

    # ── Optional RAG tool (requires PostgreSQL) ────────────────────────────────
    rag_tool = None
    if db is not None and db.available:
        try:
            from tools.rag_search import make_rag_search_tool
            rag_tool = make_rag_search_tool(db)
            logger.info("RAG tool enabled.")
        except Exception as e:
            logger.warning("RAG tool unavailable: %s", e)

    # ── Optional graph search tool (requires Apache AGE) ──────────────────────
    graph_tool = None
    if db is not None and db.available:
        try:
            from tools.graph_search import make_graph_search_tool
            graph_tool = make_graph_search_tool(db)
            logger.info("Graph search tool enabled.")
        except Exception as e:
            logger.debug("Graph search tool unavailable: %s", e)

    # ── Optional Mem0 long-term knowledge tool ────────────────────────────────
    mem0_long_term_tool = None
    mem0_entity_tool = None
    if memory_manager is not None and hasattr(memory_manager, "long_term_available"):
        if memory_manager.long_term_available:
            try:
                from tools.mem0_search import make_mem0_entity_tool, make_mem0_search_tool
                mem0_long_term_tool = make_mem0_search_tool(memory_manager)
                mem0_entity_tool = make_mem0_entity_tool(memory_manager)
                logger.info("Mem0 long-term knowledge tool enabled.")
            except Exception as e:
                logger.warning("Mem0 long-term tool unavailable: %s", e)

    def _extra_tools() -> List[StructuredTool]:
        extras = []
        if rag_tool:
            extras.append(rag_tool)
        if graph_tool:
            extras.append(graph_tool)
        if mem0_long_term_tool:
            extras.append(mem0_long_term_tool)
        if mem0_entity_tool:
            extras.append(mem0_entity_tool)
        return extras

    # ── Self-healing wrapper (optional) ──────────────────────────────────────
    def _maybe_wrap_with_healing(tools: List[StructuredTool]) -> List[StructuredTool]:
        """Optionally wrap tools with self-healing capability."""
        if ENABLE_SELF_HEALING and HEALING_AVAILABLE:
            # MCP tools already include robust retry/dedup/error handling in the
            # transport layer. Wrapping StructuredTools here creates nested tool
            # events (wrapper + inner MCP call), which inflates call counts and
            # can trigger apparent call storms in telemetry/UI.
            logger.info("Self-healing wrappers are skipped for MCP tools to avoid nested duplicate calls.")
            return tools
        return tools

    # ── Specialist sub-graphs (create_agent) ─────────────────────────────
    # Prompts are injected per-request in _make_specialist_node so that
    # long-term memory context can be prepended before each inference.
    aviation_agent = create_agent(
        llm,
        tools=_maybe_wrap_with_healing(aviation_tools + [lookup_airport_codes] + _extra_tools()),
    )
    hk_agent = create_agent(
        llm,
        tools=_maybe_wrap_with_healing(hk_tools + _extra_tools()),
    )
    aircraft_agent = create_agent(
        llm,
        tools=_maybe_wrap_with_healing(adsb_tools + [lookup_airport_codes] + _extra_tools()),
    )
    general_agent = create_agent(
        llm,
        tools=_maybe_wrap_with_healing(aviation_tools + hk_tools + adsb_tools + [lookup_airport_codes] + _extra_tools()),
    )

    if ENABLE_SELF_HEALING and HEALING_AVAILABLE:
        logger.info("Self-healing enabled for tool execution.")

    # ── Router node ────────────────────────────────────────────────────────────
    @traceable(name="orchestrator.router", run_type="chain")
    def router_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
        _annotate_thread_metadata(config)
        human_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        latest = human_msgs[-1].content if human_msgs else ""

        # Assistant-level route override (from deployment assistant config).
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        if isinstance(configurable, dict):
            forced_route = str(configurable.get("forced_route", "") or "").strip().lower()
            allowed = {"aviation_weather", "hk_weather", "aircraft", "general", "planning"}
            if forced_route in allowed:
                if forced_route == "planning" and (not ENABLE_PLANNING or not PLANNING_AVAILABLE):
                    logger.info("Router override requested planning but planning unavailable; falling back to general")
                    return {"route": "general"}
                logger.info("Router override from assistant config: %s", forced_route)
                return {"route": forced_route}

        # Deterministic overrides to avoid LLM router drift.
        latest_lower = latest.lower()

        # CRITICAL: Aviation tokens ALWAYS take priority over location tokens.
        # This ensures "metar for vhhh" routes to aviation, not HK weather.
        aviation_tokens = (
            "metar", "taf", "pirep", "airmet", "sigmet", "vfr", "ifr",
            "cloud base", "ceiling", "notam", "runway", "flight category",
            "weather briefing", "aviation weather", "airport weather",
        )

        aircraft_tokens = (
            "aircraft", "ads-b", "adsb", "flight tracking", "callsign",
            "registration", "icao24", "squawk", "arrivals", "departures",
            "flying over", "air traffic", "live flights",
        )

        planning_tokens = ("compare", "versus", "vs", "both", "difference", "differences")

        # Planning override first for explicit comparison/sequencing queries.
        if any(token in latest_lower for token in planning_tokens) and ENABLE_PLANNING and PLANNING_AVAILABLE:
            logger.info("Router override: explicit comparison forced to planning")
            return {"route": "planning"}

        # Aircraft/traffic intent should route to ADS-B specialist before
        # location-based HK overrides.
        if any(token in latest_lower for token in aircraft_tokens):
            logger.info("Router override: aircraft intent forced to aircraft")
            return {"route": "aircraft"}

        # Check aviation intent FIRST - highest priority
        if any(token in latest_lower for token in aviation_tokens):
            logger.info("Router override: aviation intent forced to aviation_weather")
            return {"route": "aviation_weather"}

        # HK civic weather tokens (NOT aviation)
        hk_weather_tokens = (
            "hko", "rainstorm", "typhoon signal", "warning signal",
            "visibility hk", "hk weather", "humidity hk", "temperature hk",
            "hong kong forecast", "hk forecast",
        )

        hk_tokens = ("hong kong", "hkg", "vhhh", "hkia")
        hk_airport_tokens = ("airport", "hkg", "vhhh", "hkia", "metar", "taf")

        if any(token in latest_lower for token in hk_tokens) and not any(
            token in latest_lower for token in planning_tokens
        ):
            # Route civic/general HK weather to HK specialist unless airport-specific intent.
            is_airport_context = any(token in latest_lower for token in hk_airport_tokens)
            if any(token in latest_lower for token in hk_weather_tokens) or (
                "weather" in latest_lower and not is_airport_context
            ):
                logger.info("Router override: HK civic weather forced to hk_weather")
                return {"route": "hk_weather"}

            # Default Hong Kong airport questions to aviation tools
            # (METAR/TAF, flight-category style briefings).
            logger.info("Router override: HK airport context forced to aviation_weather")
            return {"route": "aviation_weather"}

        response = router_llm.invoke([
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=latest),
        ])
        raw = response.content.strip().lower()

        if "aviation" in raw:
            route = "aviation_weather"
        elif "hk" in raw or "hong" in raw:
            route = "hk_weather"
        elif "aircraft" in raw:
            route = "aircraft"
        elif "planning" in raw and ENABLE_PLANNING and PLANNING_AVAILABLE:
            route = "planning"
        else:
            route = "general"

        logger.info("Router: '%s...' → %s", latest[:80], route)
        return {"route": route}

    def pick_specialist(state: AgentState) -> str:
        return state.get("route", "general")

    # ── Specialist wrapper nodes with context trimming + memory injection ────────
    # Each wrapper trims the message history before calling the sub-graph so the
    # specialist LLM never receives more than MAX_HISTORY_MESSAGES messages.
    # The base_prompt is prepended as a SystemMessage so long-term memory context
    # can be appended to it per-request without rebuilding the graph.

    def _make_specialist_node(agent_graph, base_prompt: str, specialist_name: str):
        @traceable(name=f"orchestrator.specialist.{specialist_name}", run_type="chain")
        async def node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
            _annotate_thread_metadata(config)
            trimmed = _trim_messages(state["messages"])

            # Resolve session_id for memory lookup
            session_id = config.get("configurable", {}).get("thread_id", "default")
            human_msgs = [m for m in trimmed if isinstance(m, HumanMessage)]
            latest_query = human_msgs[-1].content if human_msgs else ""

            # Inject dual memories (short-term + long-term) into the system prompt
            system_content = base_prompt
            configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
            if isinstance(configurable, dict):
                assistant_prompt = str(configurable.get("assistant_system_prompt", "") or "").strip()
                if assistant_prompt:
                    # Assistant prompt is prepended so domain prompt still enforces hard constraints.
                    system_content = f"{assistant_prompt}\n\n{base_prompt}"
            if memory_manager is not None:
                # Use search_combined for both short-term and long-term memory context.
                if hasattr(memory_manager, "search_combined"):
                    # DualMemoryManager: get both memory types
                    memories = await memory_manager.search_combined(
                        latest_query,
                        user_id=session_id,
                        session_id=session_id,
                        short_term_limit=3,
                        session_long_term_limit=2,
                        common_long_term_limit=2,
                    )
                else:
                    # Fallback for legacy MemoryManager (short-term only)
                    memories = await memory_manager.search(latest_query, user_id=session_id)

                if memories:
                    system_content = f"{base_prompt}\n\n## Memory Context\n{memories}"

            messages_to_send = [SystemMessage(content=system_content)] + trimmed

            sub_config: RunnableConfig = {
                "callbacks":       config.get("callbacks"),
                "recursion_limit": SPECIALIST_RECURSION_LIMIT,
            }
            result = await agent_graph.ainvoke(
                {"messages": messages_to_send}, config=sub_config
            )
            return {"messages": result["messages"]}
        return node

    # ── Planning node (for complex multi-step queries) ─────────────────────────
    @traceable(name="orchestrator.planning", run_type="chain")
    async def planning_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
        """Handle complex queries with plan-and-execute pattern."""
        _annotate_thread_metadata(config)
        if not PLANNING_AVAILABLE:
            # Fallback to general if planning not available
            return await _make_specialist_node(
                general_agent,
                GENERAL_PROMPT,
                "general",
            )(state, config)

        trimmed = _trim_messages(state["messages"])
        human_msgs = [m for m in trimmed if isinstance(m, HumanMessage)]
        latest_query = human_msgs[-1].content if human_msgs else ""

        # Build plan-execute graph with general agent as executor
        llm_config = _resolve_llm_config(config)
        plan_graph = build_plan_execute_graph(general_agent, llm_config)

        # Execute plan
        result = await plan_graph.ainvoke(
            {"input": latest_query},
            config={
                "callbacks": config.get("callbacks"),
                "recursion_limit": PLANNING_RECURSION_LIMIT,
                "executor_recursion_limit": int(os.getenv("PLANNING_EXECUTOR_RECURSION_LIMIT", "12")),
            },
        )

        # Return response as AI message
        from langchain_core.messages import AIMessage
        response_content = result.get("response", "Unable to complete multi-step analysis.")
        planning_data = {
            "mode": "plan_execute",
            "query": latest_query,
            "plan": result.get("original_plan", []),
            "execution_trace": result.get("execution_trace", []),
            "total_steps": len(result.get("execution_trace", [])),
        }

        return {
            "messages": trimmed + [
                AIMessage(content=response_content, additional_kwargs={"planning": planning_data})
            ],
            "planning_data": planning_data,
        }

    # ── Assemble graph ─────────────────────────────────────────────────────────
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node(
        "aviation_weather",
        _make_specialist_node(aviation_agent, AVIATION_PROMPT, "aviation_weather"),
    )
    graph.add_node(
        "hk_weather",
        _make_specialist_node(hk_agent, HK_PROMPT, "hk_weather"),
    )
    graph.add_node(
        "aircraft",
        _make_specialist_node(aircraft_agent, AIRCRAFT_PROMPT, "aircraft"),
    )
    graph.add_node(
        "general",
        _make_specialist_node(general_agent, GENERAL_PROMPT, "general"),
    )

    # Add planning node if available
    if ENABLE_PLANNING and PLANNING_AVAILABLE:
        graph.add_node("planning", planning_node)

    graph.add_edge(START, "router")

    # Build conditional routing
    route_map = {
        "aviation_weather": "aviation_weather",
        "hk_weather":       "hk_weather",
        "aircraft":         "aircraft",
        "general":          "general",
    }
    if ENABLE_PLANNING and PLANNING_AVAILABLE:
        route_map["planning"] = "planning"

    graph.add_conditional_edges(
        "router",
        pick_specialist,
        route_map,
    )

    for specialist in ("aviation_weather", "hk_weather", "aircraft", "general"):
        graph.add_edge(specialist, END)

    if ENABLE_PLANNING and PLANNING_AVAILABLE:
        graph.add_edge("planning", END)

    return graph.compile(checkpointer=checkpointer)


# ── Public startup helper ─────────────────────────────────────────────────────

async def init_graph(memory_manager=None, db=None):
    """
    Start MCP servers, build LangGraph graph, return
    (compiled_graph, mcp_client_instance, checkpointer).
    """
    client = mcp_module.MCPClient()
    client.load_servers(str(CONFIG_FILE))
    tools_by_server = await client.start_langchain()

    aviation_tools = tools_by_server.get("aviation-weather", [])
    hk_tools       = tools_by_server.get("hk-climate", [])
    adsb_tools     = tools_by_server.get("adsb", [])

    logger.info(
        "MCP tools loaded — aviation: %d, hk: %d, adsb: %d",
        len(aviation_tools), len(hk_tools), len(adsb_tools),
    )

    checkpointer = MemorySaver()
    graph = _build_graph(
        aviation_tools, hk_tools, adsb_tools, checkpointer,
        memory_manager=memory_manager, db=db,
    )
    return graph, client, checkpointer


# ── CLI entry-point ───────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(level=logging.INFO)
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    graph, mcp_client_instance, _ = await init_graph()
    config = {"configurable": {"thread_id": "cli-session"}}

    try:
        while True:
            try:
                user_input = input("\n[You] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.lower() in ("exit", "quit", "bye"):
                break
            if not user_input:
                continue

            console.print("\n[bold blue][Assistant][/bold blue]")
            full = ""
            async for ev in graph.astream_events(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
                version="v2",
            ):
                kind = ev.get("event", "")
                meta = ev.get("metadata", {})
                node = meta.get("langgraph_node", "")

                if kind == "on_chat_model_stream" and node != "router":
                    chunk = ev["data"]["chunk"]
                    token = chunk.content if hasattr(chunk, "content") else ""
                    if token:
                        full += token
                        print(token, end="", flush=True)
                elif kind == "on_tool_start":
                    tool_name = ev.get("name", "tool")
                    console.print(
                        f"\n[dim]  ⚙  {tool_name}({json.dumps(ev['data'].get('input', {}))[:120]})[/dim]"
                    )
                elif kind == "on_tool_end":
                    console.print("[dim]  ✓  done[/dim]")

            print()
            if full:
                console.print(Markdown(full))
    finally:
        await mcp_client_instance.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
