"""
FastAPI server for the LangGraph aviation weather agent.
"""
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from db import Database
from memory import DualMemoryManager  # Upgraded from MemoryManager
from cache import CacheManager
from orchestrator import init_graph

logger = logging.getLogger(__name__)

# ── Module-level singletons ────────────────────────────────────────────────────

db             = Database()
memory_manager = DualMemoryManager()  # Unified short-term (mem0) + long-term (cognee)
cache          = CacheManager()       # Redis cache for frequently-asked queries

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_graph, global_mcp_client

    # Startup
    await db.connect()
    await memory_manager.init()
    await cache.init()  # Initialize Redis cache

    scheduler = None
    if db.available:
        try:
            from ingestion.scheduler import setup_scheduler
            scheduler = setup_scheduler(db)
        except Exception as e:
            logger.warning("Ingestion scheduler unavailable: %s", e)

    print("Initialising LangGraph agent with MCP servers…")
    try:
        global_graph, global_mcp_client, _ = await init_graph(
            memory_manager=memory_manager, db=db,
        )
        print("LangGraph agent ready.")
    except Exception:
        import traceback
        traceback.print_exc()
        raise

    yield

    # Shutdown
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
    if global_mcp_client:
        print("Shutting down MCP client…")
        await global_mcp_client.cleanup()
    await db.close()
    await cache.close()  # Close Redis connection


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Basic liveness endpoint for orchestrator and health-check utility."""
    return {
        "status": "ok",
        "service": "agent",
        "version": "1.0.0",
    }

# ── Globals ────────────────────────────────────────────────────────────────────

global_graph = None
global_mcp_client = None
event_queues: Dict[str, asyncio.Queue] = {}

SPECIALIST_NODES = {"aviation_weather", "hk_weather", "aircraft", "general", "planning"}

_NODE_LABELS: Dict[str, str] = {
    "router":           "Router",
    "aviation_weather": "Aviation Weather",
    "hk_weather":       "HK Weather",
    "aircraft":         "Aircraft Tracking",
    "general":          "General Assistant",
    "planning":         "Multi-Step Planner",
    "plan":             "Plan Builder",
    "execute":          "Plan Step Executor",
    "synthesize":       "Final Synthesizer",
}

PLANNING_INTERNAL_NODES = {"plan", "execute", "synthesize"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_planning_data(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract planning metadata from graph result payload or final AI message."""
    if not result:
        return None

    planning_data = result.get("planning_data")
    if isinstance(planning_data, dict):
        return planning_data

    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            maybe = getattr(msg, "additional_kwargs", {}).get("planning")
            if isinstance(maybe, dict):
                return maybe
    return None


# ── Langfuse (optional) ───────────────────────────────────────────────────────

def _make_langfuse_callback(session_id: str, trace_name: str):
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler(session_id=session_id, trace_name=trace_name)
    except Exception as e:
        logger.warning("Langfuse callback unavailable: %s", e)
        return None


def _build_config(session_id: str, trace_name: str = "") -> dict:
    cfg: dict = {"configurable": {"thread_id": session_id}}
    lf = _make_langfuse_callback(session_id, trace_name or session_id)
    if lf:
        cfg["callbacks"] = [lf]
    return cfg


# ── Workflow-event SSE helpers ─────────────────────────────────────────────────

async def _push(session_id: str, data: Dict[str, Any]) -> None:
    q = event_queues.get(session_id)
    if q:
        await q.put(json.dumps(data))


def _fmt_input(raw: Any) -> str:
    """Short readable summary of a tool-input dict."""
    if isinstance(raw, dict):
        parts = [f"{k}={repr(v)[:40]}" for k, v in list(raw.items())[:4]]
        return ", ".join(parts)
    return str(raw)[:100]


def _tool_call_names(tool_calls: list) -> str:
    """Return a comma-separated string of tool call names."""
    names = []
    for tc in tool_calls[:6]:  # cap at 6
        if isinstance(tc, dict):
            names.append(tc.get("name", "?"))
        elif hasattr(tc, "name"):
            names.append(tc.name)
    return ", ".join(names)


async def _run_with_events(user_input: str, session_id: str) -> None:
    """Run graph and push rich SSE workflow events into the session queue."""
    if not global_graph:
        await _push(session_id, {
            "nodeId": "error", "event_type": "error",
            "status": "failed", "details": "Agent not initialised",
            "timestamp": _now_iso(), "raw": {},
        })
        await _push(session_id, {"__done__": True})
        return

    config = _build_config(session_id, trace_name=user_input[:80])
    active_nodes: set[str] = set()
    node_start: dict[str, float] = {}
    tool_start: dict[str, float] = {}
    current_specialist: str = ""
    routing_emitted: bool = False
    router_started_at: float = 0.0

    # Per-session step tracking (counts LLM → tool-call rounds in a specialist)
    step_counts: dict[str, int] = {}   # keyed by specialist node name

    INTERNAL = {"agent", "tools", *PLANNING_INTERNAL_NODES}
    INTERNAL_LABELS = {"agent": "LLM Call", "tools": "Tool Execution"}

    try:
        async for ev in global_graph.astream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v2",
        ):
            kind    = ev.get("event", "")
            meta    = ev.get("metadata", {})
            node    = meta.get("langgraph_node", "")
            ts      = _now_iso()

            # ── Node started ───────────────────────────────────────────────────
            if kind == "on_chain_start" and node and node not in active_nodes:
                active_nodes.add(node)
                node_start[node] = time.monotonic()
                if node == "router":
                    router_started_at = time.monotonic()

                if node in SPECIALIST_NODES:
                    current_specialist = node
                    step_counts[node] = 0
                    if not routing_emitted:
                        routing_emitted = True
                        router_dur = int(
                            (time.monotonic() - router_started_at) * 1000
                        ) if router_started_at else 0
                        await _push(session_id, {
                            "nodeId": "router",
                            "event_type": "routing_decision",
                            "status": "completed",
                            "label": f"Router → {node}",
                            "details": f"Query classified as: {node}",
                            "route": node,
                            "duration_ms": router_dur,
                            "timestamp": ts,
                            "raw": {"node": "router", "route": node},
                        })

                label      = INTERNAL_LABELS.get(node) or _NODE_LABELS.get(node, node)
                event_type = "internal" if node in INTERNAL else "node"
                await _push(session_id, {
                    "nodeId":      node,
                    "event_type":  event_type,
                    "status":      "started",
                    "label":       label,
                    "details":     f"{label}: processing…",
                    "parent_node": current_specialist if node in INTERNAL else None,
                    "timestamp":   ts,
                    "raw":         {"node": node},
                })

            # ── Node completed ─────────────────────────────────────────────────
            elif kind == "on_chain_end" and node and node in active_nodes:
                active_nodes.discard(node)
                duration_ms = int(
                    (time.monotonic() - node_start.pop(node, time.monotonic())) * 1000
                )
                if node in SPECIALIST_NODES:
                    total_steps = step_counts.pop(node, 0)
                    current_specialist = ""

                label      = INTERNAL_LABELS.get(node) or _NODE_LABELS.get(node, node)
                event_type = "internal" if node in INTERNAL else "node"

                if node != "router" or not routing_emitted:
                    steps_note = ""
                    if node in SPECIALIST_NODES:
                        steps_note = f" ({total_steps} reasoning step{'s' if total_steps != 1 else ''})"
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  event_type,
                        "status":      "completed",
                        "label":       label,
                        "details":     f"{label} finished{steps_note}.",
                        "parent_node": current_specialist if node in INTERNAL else None,
                        "duration_ms": duration_ms,
                        "timestamp":   ts,
                        "raw":         {"node": node, "steps": total_steps if node in SPECIALIST_NODES else None},
                    })

                # Emit plan details when the planner node completes.
                if node == "plan":
                    output = ev.get("data", {}).get("output", {})
                    plan_steps = output.get("original_plan") or output.get("plan") or []
                    if plan_steps:
                        await _push(session_id, {
                            "nodeId": "planning",
                            "event_type": "plan",
                            "status": "completed",
                            "label": "Execution Plan",
                            "details": f"Generated {len(plan_steps)} steps",
                            "steps": plan_steps,
                            "timestamp": ts,
                            "raw": {"steps": plan_steps},
                        })

            # ── LLM completed a generation (reasoning event) ───────────────────
            elif kind == "on_chat_model_end" and node and node not in ("router",):
                output     = ev["data"].get("output")
                tool_calls = []
                content    = ""

                if output is not None:
                    if hasattr(output, "tool_calls"):
                        tool_calls = output.tool_calls or []
                    if hasattr(output, "content"):
                        content = output.content or ""
                    # Some models return generations list
                    elif hasattr(output, "generations"):
                        for gen_list in output.generations:
                            for gen in gen_list:
                                msg = getattr(gen, "message", None)
                                if msg:
                                    tool_calls = getattr(msg, "tool_calls", []) or tool_calls
                                    content    = getattr(msg, "content", "") or content

                parent = current_specialist or node

                if tool_calls:
                    # LLM decided to make tool calls → planning step
                    n   = len(tool_calls)
                    tc_names = _tool_call_names(tool_calls)
                    step_num = step_counts.get(parent, 0) + 1
                    step_counts[parent] = step_num
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  "reasoning",
                        "status":      "completed",
                        "label":       f"Step {step_num}: Planning",
                        "details":     f"Planned {n} tool call{'s' if n != 1 else ''}: {tc_names}",
                        "parent_node": parent if parent != node else None,
                        "step":        step_num,
                        "timestamp":   ts,
                        "raw":         {
                            "node":       node,
                            "step":       step_num,
                            "tool_calls": [
                                (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?"))
                                for tc in tool_calls
                            ],
                        },
                    })
                elif content:
                    # LLM generated a final response → synthesis step
                    step_num = step_counts.get(parent, 0) + 1
                    step_counts[parent] = step_num
                    preview  = content[:120].replace("\n", " ")
                    await _push(session_id, {
                        "nodeId":      node,
                        "event_type":  "reasoning",
                        "status":      "completed",
                        "label":       f"Step {step_num}: Synthesis",
                        "details":     f"Final answer: {preview}{'…' if len(content) > 120 else ''}",
                        "parent_node": parent if parent != node else None,
                        "step":        step_num,
                        "timestamp":   ts,
                        "raw":         {
                            "node":    node,
                            "step":    step_num,
                            "preview": preview,
                        },
                    })

            # ── Tool call started ─────────────────────────────────────────────
            elif kind == "on_tool_start":
                tool_name  = ev.get("name", "tool")
                tool_input = ev["data"].get("input", {})
                tool_start[tool_name] = time.monotonic()
                parent     = current_specialist or meta.get("langgraph_node", "")

                await _push(session_id, {
                    "nodeId":      tool_name,
                    "event_type":  "tool",
                    "status":      "started",
                    "label":       tool_name,
                    "details":     f"Calling {tool_name}({_fmt_input(tool_input)})",
                    "tool_input":  tool_input if isinstance(tool_input, dict) else {},
                    "parent_node": parent,
                    "timestamp":   ts,
                    "raw":         {"tool": tool_name, "input": tool_input, "parent": parent},
                })

            # ── Tool call completed ───────────────────────────────────────────
            elif kind == "on_tool_end":
                tool_name   = ev.get("name", "tool")
                duration_ms = int(
                    (time.monotonic() - tool_start.pop(tool_name, time.monotonic())) * 1000
                )
                output          = ev["data"].get("output", "")
                output_str      = str(output) if output else ""
                output_preview  = output_str[:200]
                output_chars    = len(output_str)
                parent          = current_specialist or meta.get("langgraph_node", "")

                await _push(session_id, {
                    "nodeId":       tool_name,
                    "event_type":   "tool",
                    "status":       "completed",
                    "label":        tool_name,
                    "details":      (
                        f"{tool_name} → {output_preview[:80]}"
                        f"{'…' if len(output_preview) > 80 else ''}"
                        f"  ({output_chars} chars)"
                    ),
                    "parent_node":  parent,
                    "duration_ms":  duration_ms,
                    "timestamp":    ts,
                    "raw":          {
                        "tool":           tool_name,
                        "output_preview": output_preview,
                        "output_chars":   output_chars,
                        "parent":         parent,
                    },
                })

    except Exception as e:
        logger.exception("Orchestration error for session %s", session_id)
        await _push(session_id, {
            "nodeId": "error", "event_type": "error", "status": "failed",
            "details": f"Error: {e}", "timestamp": _now_iso(), "raw": {"error": str(e)},
        })
    finally:
        await _push(session_id, {"__done__": True})


# ── POST /api/agent/execute ────────────────────────────────────────────────────

@app.post("/api/agent/execute")
async def execute_workflow(request: Request):
    data       = await request.json()
    user_input = data.get("input", "")
    session_id = data.get("session_id", "default")

    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)
    event_queues[session_id] = asyncio.Queue()
    asyncio.create_task(_run_with_events(user_input, session_id))
    return JSONResponse({"status": "started", "session_id": session_id})


# ── GET /api/agent/events ──────────────────────────────────────────────────────

@app.get("/api/agent/events")
async def stream_events(session_id: str = "default"):
    async def event_stream():
        waited, interval, deadline = 0.0, 0.05, 10.0
        while session_id not in event_queues and waited < deadline:
            await asyncio.sleep(interval)
            waited += interval

        q: Optional[asyncio.Queue] = event_queues.get(session_id)
        if q is None:
            yield "event: end\ndata: {}\n\n"
            return

        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                try:
                    if json.loads(raw).get("__done__"):
                        yield "event: end\ndata: {}\n\n"
                        break
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield f"data: {raw}\n\n"
        finally:
            event_queues.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /api/agent/stream ──────────────────────────────────────────────────────

@app.get("/api/agent/stream")
async def stream_chat(input: str = "", session_id: str = "default"):
    if not input:
        return JSONResponse({"error": "No input provided"}, status_code=400)
    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)

    config = _build_config(session_id, trace_name=input[:80])

    async def stream_tokens():
        current_specialist = ""
        tool_start_times: Dict[str, float] = {}
        step_counts: Dict[str, int] = {}
        router_start = 0.0

        try:
            async for ev in global_graph.astream_events(
                {"messages": [HumanMessage(content=input)]},
                config=config,
                version="v2",
            ):
                kind = ev.get("event", "")
                meta = ev.get("metadata", {})
                node = meta.get("langgraph_node", "")
                ts = _now_iso()

                # ── Routing decision ─────────────────────────────────────────
                if kind == "on_chain_start" and node == "router":
                    router_start = time.monotonic()

                if kind == "on_chain_start" and node in SPECIALIST_NODES:
                    current_specialist = node
                    step_counts[node] = 0
                    router_dur = int((time.monotonic() - router_start) * 1000) if router_start else 0
                    yield f"event: route\ndata: {json.dumps({'route': node, 'specialist': node, 'duration': router_dur, 'timestamp': ts})}\n\n"

                # Planning internals: emit explicit plan + execution-step telemetry
                if kind == "on_chain_end" and node == "plan":
                    output = ev.get("data", {}).get("output", {})
                    plan_steps = output.get("original_plan") or output.get("plan") or []
                    if plan_steps:
                        yield (
                            "event: plan\n"
                            f"data: {json.dumps({'plan': plan_steps, 'steps': plan_steps, 'timestamp': ts})}\n\n"
                        )

                if kind == "on_chain_end" and node == "execute":
                    output = ev.get("data", {}).get("output", {})
                    trace = output.get("execution_trace") or []
                    if trace:
                        latest = trace[-1]
                        step_num = int(latest.get("step", len(trace)))
                        task = latest.get("task", "")
                        preview = latest.get("result", "")[:160].replace("\n", " ")
                        yield (
                            "event: thinking\n"
                            f"data: {json.dumps({'type': 'reasoning', 'thinking': f'Step {step_num}: {task}', 'result': preview, 'step': step_num, 'timestamp': ts})}\n\n"
                        )

                # ── Streaming tokens ─────────────────────────────────────────
                if kind == "on_chat_model_stream" and node != "router":
                    chunk = ev["data"]["chunk"]
                    token = chunk.content if hasattr(chunk, "content") else ""
                    if token:
                        yield f"event: chunk\ndata: {json.dumps({'chunk': token})}\n\n"

                # ── Thinking/reasoning events ────────────────────────────────
                elif kind == "on_chat_model_end" and node and node != "router":
                    output = ev["data"].get("output")
                    tool_calls = []
                    content = ""

                    if output is not None:
                        if hasattr(output, "tool_calls"):
                            tool_calls = output.tool_calls or []
                        if hasattr(output, "content"):
                            content = output.content or ""
                        elif hasattr(output, "generations"):
                            for gen_list in output.generations:
                                for gen in gen_list:
                                    msg = getattr(gen, "message", None)
                                    if msg:
                                        tool_calls = getattr(msg, "tool_calls", []) or tool_calls
                                        content = getattr(msg, "content", "") or content

                    parent = current_specialist or node

                    if tool_calls:
                        step_num = step_counts.get(parent, 0) + 1
                        step_counts[parent] = step_num
                        tc_names = _tool_call_names(tool_calls)
                        yield f"event: thinking\ndata: {json.dumps({'type': 'reasoning', 'thinking': f'Step {step_num}: Planning - {tc_names}', 'step': step_num, 'timestamp': ts})}\n\n"
                    elif content:
                        step_num = step_counts.get(parent, 0) + 1
                        step_counts[parent] = step_num
                        preview = content[:120].replace("\n", " ")
                        yield f"event: thinking\ndata: {json.dumps({'type': 'synthesis', 'thinking': f'Step {step_num}: Synthesizing response', 'result': preview, 'step': step_num, 'timestamp': ts})}\n\n"

                # ── Tool start ───────────────────────────────────────────────
                elif kind == "on_tool_start":
                    tool_name = ev.get("name", "tool")
                    tool_input = ev["data"].get("input", {})
                    tool_start_times[tool_name] = time.monotonic()
                    yield f"event: tool_start\ndata: {json.dumps({'tool_start': tool_name, 'name': tool_name, 'tool_input': tool_input, 'input': tool_input, 'timestamp': ts})}\n\n"

                # ── Tool end ─────────────────────────────────────────────────
                elif kind == "on_tool_end":
                    tool_name = ev.get("name", "tool")
                    output = ev["data"].get("output", "")
                    output_str = str(output) if output else ""
                    duration_ms = int((time.monotonic() - tool_start_times.pop(tool_name, time.monotonic())) * 1000)
                    # Truncate output for SSE (full output in workflow events)
                    output_preview = output_str[:500] if output_str else ""
                    yield f"event: tool_end\ndata: {json.dumps({'tool_end': tool_name, 'name': tool_name, 'output': output_preview, 'duration': duration_ms, 'timestamp': ts})}\n\n"

            yield "event: end\ndata: {}\n\n"
        except Exception as e:
            logger.exception("Streaming error for session %s", session_id)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        stream_tokens(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── POST /api/agent ────────────────────────────────────────────────────────────

@app.post("/api/agent")
async def chat_endpoint(request: Request):
    data       = await request.json()
    user_input = data.get("input", data.get("message", ""))
    session_id = data.get("session_id", "default")

    if not global_graph:
        return JSONResponse({"error": "Agent not initialised"}, status_code=500)

    # Check cache first (only for non-session-specific queries)
    # Cache key includes session to handle context
    route = data.get("route", "unknown")  # Optional pre-classified route
    cached_response = await cache.get_llm_response(user_input, session_id, route)
    if cached_response:
        logger.info("Cache HIT for query: %s", user_input[:80])
        return JSONResponse({"response": cached_response, "cached": True})

    config = _build_config(session_id, trace_name=user_input[:80])
    try:
        result = await global_graph.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )
        messages      = result.get("messages", [])
        ai_msgs       = [m for m in messages if hasattr(m, "content") and not isinstance(m, HumanMessage)]
        response_text = ai_msgs[-1].content if ai_msgs else "No response generated."
        detected_route = result.get("route", "general")
        planning_data = _extract_planning_data(result)

        # Persist conversation turn to postgres
        if db.available:
            await db.save_conversation(session_id, "human", user_input)
            await db.save_conversation(session_id, "ai", response_text)

        # Store short-term conversation memories (fire-and-forget, non-blocking)
        if memory_manager.short_term_available:
            asyncio.create_task(
                memory_manager.add_conversation(
                    [
                        {"role": "user",      "content": user_input},
                        {"role": "assistant", "content": response_text},
                    ],
                    user_id=session_id,
                    metadata={"route": detected_route},
                )
            )

        # Cache the response (fire-and-forget)
        asyncio.create_task(
            cache.set_llm_response(user_input, session_id, detected_route, response_text)
        )

        return JSONResponse({
            "response": response_text,
            "cached": False,
            "route": detected_route,
            "plan": planning_data.get("plan", []) if planning_data else [],
            "execution_trace": planning_data.get("execution_trace", []) if planning_data else [],
            "multi_step": bool(planning_data),
        })
    except Exception as e:
        logger.exception("Chat endpoint error for session %s", session_id)
        return JSONResponse({"response": f"Error: {e}"}, status_code=500)


# ── Knowledge Graph / Document Ingestion Endpoints ────────────────────────────


@app.post("/api/knowledge/ingest")
async def ingest_document(request: Request):
    """
    Ingest a document into long-term knowledge graph (cognee).

    Body:
        {
            "text": "document content...",
            "metadata": {"source": "NTSB", "date": "2024-01-15", ...},
            "dataset": "aviation_knowledge"  # optional
        }

    Returns:
        {"success": true} or {"success": false, "error": "..."}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"success": False, "error": "Long-term memory (cognee) unavailable"},
            status_code=503,
        )

    try:
        data = await request.json()
        text = data.get("text", "")
        metadata = data.get("metadata", {})
        dataset = data.get("dataset", "aviation_knowledge")

        if not text:
            return JSONResponse(
                {"success": False, "error": "No text provided"},
                status_code=400,
            )

        success = await memory_manager.add_knowledge(
            text=text,
            metadata=metadata,
            dataset_name=dataset,
        )

        if success:
            logger.info("Ingested document: %d chars, dataset=%s", len(text), dataset)
            return JSONResponse({"success": True, "dataset": dataset})
        else:
            return JSONResponse(
                {"success": False, "error": "Ingestion failed"},
                status_code=500,
            )

    except Exception as e:
        logger.exception("Document ingestion error")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/api/knowledge/ingest-batch")
async def ingest_documents_batch(request: Request):
    """
    Ingest multiple documents in batch.

    Body:
        {
            "documents": [
                {"text": "...", "metadata": {...}},
                {"text": "...", "metadata": {...}},
                ...
            ],
            "dataset": "aviation_knowledge"  # optional
        }

    Returns:
        {"success": N, "total": M, "failed": K}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"success": False, "error": "Long-term memory (cognee) unavailable"},
            status_code=503,
        )

    try:
        data = await request.json()
        documents = data.get("documents", [])
        dataset = data.get("dataset", "aviation_knowledge")

        if not documents:
            return JSONResponse(
                {"success": False, "error": "No documents provided"},
                status_code=400,
            )

        success_count = await memory_manager.add_knowledge_batch(
            documents=documents,
            dataset_name=dataset,
        )

        return JSONResponse({
            "success": success_count,
            "total": len(documents),
            "failed": len(documents) - success_count,
            "dataset": dataset,
        })

    except Exception as e:
        logger.exception("Batch ingestion error")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.get("/api/knowledge/search")
async def search_knowledge(
    query: str = "",
    dataset: str = "aviation_knowledge",
    limit: int = 5,
):
    """
    Search long-term knowledge graph.

    Query params:
        - query: Search query (required)
        - dataset: Dataset name (default: aviation_knowledge)
        - limit: Max results (default: 5, max: 10)

    Returns:
        {"results": "formatted knowledge graph results", "cached": bool}
    """
    if not query:
        return JSONResponse(
            {"error": "No query provided"},
            status_code=400,
        )

    if not memory_manager.long_term_available:
        return JSONResponse(
            {"results": "Long-term memory (cognee) unavailable"},
        )

    try:
        limit = max(1, min(limit, 10))

        # Check cache first
        cached_results = await cache.get_knowledge_search(query, dataset)
        if cached_results:
            logger.debug("Cache HIT for knowledge search: %s", query[:80])
            return JSONResponse({
                "query": query,
                "dataset": dataset,
                "results": cached_results,
                "cached": True,
            })

        # Cache miss: query knowledge graph
        results = await memory_manager.search_long_term(
            query=query,
            dataset_name=dataset,
            limit=limit,
        )

        # Cache the results (fire-and-forget)
        asyncio.create_task(cache.set_knowledge_search(query, dataset, results))

        return JSONResponse({
            "query": query,
            "dataset": dataset,
            "results": results or "No results found",
            "cached": False,
        })

    except Exception as e:
        logger.exception("Knowledge search error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.get("/api/knowledge/entity/{entity_name}")
async def get_entity_info(
    entity_name: str,
    dataset: str = "aviation_knowledge",
):
    """
    Retrieve entity information from knowledge graph.

    Path params:
        - entity_name: Entity identifier (e.g., "EGLL", "Boeing 737")

    Query params:
        - dataset: Dataset name (default: aviation_knowledge)

    Returns:
        {"entity": {...}} or {"error": "Not found"}
    """
    if not memory_manager.long_term_available:
        return JSONResponse(
            {"error": "Long-term memory (cognee) unavailable"},
            status_code=503,
        )

    try:
        entity = await memory_manager.get_entity(
            entity_name=entity_name,
            dataset_name=dataset,
        )

        if entity:
            return JSONResponse({"entity": entity})
        else:
            return JSONResponse(
                {"error": f"Entity not found: {entity_name}"},
                status_code=404,
            )

    except Exception as e:
        logger.exception("Entity retrieval error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.get("/api/memory/status")
async def memory_status():
    """
    Get memory system status.

    Returns:
        {
            "short_term": {"available": true, "provider": "mem0"},
            "long_term": {"available": true, "provider": "cognee"},
            "cache": {"available": true, "provider": "redis", "hit_rate": 0.85}
        }
    """
    cache_stats = await cache.get_stats() if cache.available else {"available": False}

    return JSONResponse({
        "short_term": {
            "available": memory_manager.short_term_available,
            "provider": "mem0",
            "description": "Recent conversational context (last N turns)",
        },
        "long_term": {
            "available": memory_manager.long_term_available,
            "provider": "cognee",
            "description": "Persistent knowledge graph (domain expertise)",
        },
        "cache": {
            "available": cache.available,
            "provider": "redis",
            "description": "High-performance query cache",
            **cache_stats,
        },
        "dual_memory": {
            "enabled": memory_manager.short_term_available or memory_manager.long_term_available,
            "both_available": memory_manager.short_term_available and memory_manager.long_term_available,
        },
    })


# ── Cache Management Endpoints ────────────────────────────────────────────────


@app.get("/api/cache/stats")
async def cache_stats_endpoint():
    """
    Get cache statistics (hit rate, keyspace info).

    Returns:
        {"available": true, "hit_rate": 0.85, "keyspace_hits": 1234, ...}
    """
    if not cache.available:
        return JSONResponse(
            {"available": False, "error": "Cache not available"},
            status_code=503,
        )

    try:
        stats = await cache.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.exception("Cache stats error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


# ── Phase 13/14 Data APIs ──────────────────────────────────────────────────────

_AIRPORT_COORDS: Dict[str, Dict[str, float]] = {
    "VHHH": {"lat": 22.3080, "lon": 113.9185},
    "EGLL": {"lat": 51.4700, "lon": -0.4543},
    "KJFK": {"lat": 40.6413, "lon": -73.7781},
    "WSSS": {"lat": 1.3644, "lon": 103.9915},
    "OMDB": {"lat": 25.2532, "lon": 55.3657},
    "RJTT": {"lat": 35.5494, "lon": 139.7798},
    "YSSY": {"lat": -33.9399, "lon": 151.1753},
    "LFPG": {"lat": 49.0097, "lon": 2.5479},
}


@app.get("/api/visualizations/airport-map")
async def airport_map_data(limit: int = 12):
    if not db.available:
        return JSONResponse({"airports": [], "error": "Database unavailable"}, status_code=503)
    rows = await db.latest_metar_by_airport(limit=limit)
    airports = []
    for r in rows:
        icao = str(r["icao"]).strip().upper()
        coords = _AIRPORT_COORDS.get(icao)
        if not coords:
            continue
        airports.append({
            "icao": icao,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "obs_time": r["obs_time"].isoformat() if r["obs_time"] else None,
            "flight_cat": r["flight_cat"],
            "temp_c": r["temp_c"],
            "wind_speed_kt": r["wind_speed_kt"],
            "visibility_sm": r["visibility_sm"],
        })
    return JSONResponse({"airports": airports})


@app.get("/api/visualizations/weather-trends")
async def weather_trends_data(icaos: str = "VHHH,EGLL,KJFK", hours: int = 72):
    if not db.available:
        return JSONResponse({"points": [], "error": "Database unavailable"}, status_code=503)
    selected = [x.strip().upper()[:4] for x in icaos.split(",") if x.strip()]
    rows = await db.metar_trends(selected, hours=hours)
    points = [
        {
            "icao": str(r["icao"]).strip().upper(),
            "obs_time": r["obs_time"].isoformat() if r["obs_time"] else None,
            "wind_speed_kt": r["wind_speed_kt"],
            "temp_c": r["temp_c"],
        }
        for r in rows
    ]
    return JSONResponse({"points": points, "icaos": selected, "hours": hours})


@app.get("/api/visualizations/flight-paths")
async def flight_paths_data(limit: int = 8):
    """
    Build simple route-like edges from airport coordinates for workflow-style path viz.
    """
    selected = list(_AIRPORT_COORDS.keys())[: max(2, min(limit, len(_AIRPORT_COORDS)))]
    nodes = [
        {"id": icao, "label": icao, "lat": _AIRPORT_COORDS[icao]["lat"], "lon": _AIRPORT_COORDS[icao]["lon"]}
        for icao in selected
    ]
    edges = []
    for i in range(len(selected) - 1):
        src = selected[i]
        dst = selected[i + 1]
        edges.append({"id": f"{src}-{dst}", "source": src, "target": dst})
    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/api/visualizations/safety-heatmap")
async def safety_heatmap_data(limit: int = 20):
    if not db.available:
        return JSONResponse({"cells": [], "error": "Database unavailable"}, status_code=503)
    rows = await db.safety_heatmap(limit=limit)
    cells = []
    for r in rows:
        icao = str(r["airport_icao"]).strip().upper()
        coords = _AIRPORT_COORDS.get(icao)
        if not coords:
            continue
        cells.append({
            "icao": icao,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "incidents": int(r["incidents"]),
            "severity_score": int(r["severity_score"]),
        })
    return JSONResponse({"cells": cells})


@app.post("/api/performance/refresh-airport-stats")
async def refresh_airport_stats():
    if not db.available:
        return JSONResponse({"refreshed": False, "error": "Database unavailable"}, status_code=503)
    refreshed = await db.refresh_airport_stats()
    if not refreshed:
        return JSONResponse(
            {"refreshed": False, "error": "airport_stats materialized view not found"},
            status_code=404,
        )
    top = await db.airport_stats_view()
    return JSONResponse(
        {
            "refreshed": True,
            "top": [{"icao": r["icao"], "avg_wind": r["avg_wind"], "metar_count": r["metar_count"]} for r in top],
        }
    )


@app.post("/api/cache/clear")
async def clear_cache(request: Request):
    """
    Clear cache by pattern.

    Body:
        {"pattern": "weather:*"}  # pattern to clear (default: all)

    Returns:
        {"cleared": N}  # number of keys deleted
    """
    if not cache.available:
        return JSONResponse(
            {"error": "Cache not available"},
            status_code=503,
        )

    try:
        data = await request.json()
        pattern = data.get("pattern", "*")  # default: clear all

        cleared = await cache.clear_pattern(pattern)
        return JSONResponse({"cleared": cleared, "pattern": pattern})
    except Exception as e:
        logger.exception("Cache clear error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.post("/api/cache/invalidate-knowledge")
async def invalidate_knowledge_cache():
    """
    Invalidate all knowledge graph caches.

    Use this after batch document ingestion to ensure fresh results.

    Returns:
        {"cleared": N}
    """
    if not cache.available:
        return JSONResponse(
            {"error": "Cache not available"},
            status_code=503,
        )

    try:
        cleared = await cache.invalidate_knowledge_cache()
        return JSONResponse({
            "cleared": cleared,
            "message": "Knowledge graph cache invalidated",
        })
    except Exception as e:
        logger.exception("Knowledge cache invalidation error")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
