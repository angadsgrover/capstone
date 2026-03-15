"""
FastAPI server for the LangGraph aviation weather agent.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage

from orchestrator import init_graph

logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Globals ────────────────────────────────────────────────────────────────────

global_graph = None
global_mcp_client = None
event_queues: Dict[str, asyncio.Queue] = {}

SPECIALIST_NODES = {"aviation_weather", "hk_weather", "aircraft", "general"}

_NODE_LABELS: Dict[str, str] = {
    "router":           "Router",
    "aviation_weather": "Aviation Weather",
    "hk_weather":       "HK Weather",
    "aircraft":         "Aircraft Tracking",
    "general":          "General Assistant",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Startup / shutdown ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    global global_graph, global_mcp_client
    print("Initialising LangGraph agent with MCP servers…")
    try:
        global_graph, global_mcp_client, _ = await init_graph()
        print("LangGraph agent ready.")
    except Exception:
        import traceback
        traceback.print_exc()
        raise


@app.on_event("shutdown")
async def shutdown_event():
    if global_mcp_client:
        print("Shutting down MCP client…")
        await global_mcp_client.cleanup()


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

    INTERNAL = {"agent", "tools"}
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
        try:
            async for ev in global_graph.astream_events(
                {"messages": [HumanMessage(content=input)]},
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
                        yield f"data: {json.dumps({'chunk': token})}\n\n"

                elif kind == "on_tool_start":
                    tool_name  = ev.get("name", "tool")
                    tool_input = ev["data"].get("input", {})
                    yield f"data: {json.dumps({'tool_start': tool_name, 'tool_input': _fmt_input(tool_input)})}\n\n"

                elif kind == "on_tool_end":
                    tool_name = ev.get("name", "tool")
                    yield f"data: {json.dumps({'tool_end': tool_name})}\n\n"

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

    config = _build_config(session_id, trace_name=user_input[:80])
    try:
        result = await global_graph.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )
        messages   = result.get("messages", [])
        ai_msgs    = [m for m in messages if hasattr(m, "content") and not isinstance(m, HumanMessage)]
        response_text = ai_msgs[-1].content if ai_msgs else "No response generated."
        return JSONResponse({"response": response_text})
    except Exception as e:
        logger.exception("Chat endpoint error for session %s", session_id)
        return JSONResponse({"response": f"Error: {e}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
