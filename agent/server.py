"""
FastAPI server for the simplified weather agent.
Maintains compatibility with the existing frontend by providing the same API endpoints.
"""
import asyncio
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import queue
import json

# Import the simplified orchestrator
from orchestrator import get_weather_agent, get_model # Adjust import path if necessary

app = FastAPI()

# Allow CORS for local frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent and client instances to avoid repeated MCP server startup/shutdown
global_mcp_client = None
global_agent = None
global_model = None

# In-memory event queue for SSE (per session in-memory, not production safe)
event_queues: Dict[str, "queue.Queue[str]"] = {}

@app.on_event("startup")
async def startup_event():
    global global_mcp_client, global_agent, global_model
    print("Initializing global weather agent with MCP servers...")
    try:
        global_mcp_client, global_agent = await get_weather_agent()
        global_model = get_model() # Store model instance if needed elsewhere
        print("Global weather agent initialized successfully")
    except Exception as e:
        print(f"ERROR: Failed to initialize weather agent: {e}")
        import traceback
        traceback.print_exc()
        raise

@app.on_event("shutdown")
async def shutdown_event():
    global global_mcp_client
    if global_mcp_client:
        print("Shutting down global MCP client...")
        await global_mcp_client.cleanup()
        print("Global MCP client shut down.")

# Create a lock to handle concurrent access to the agent
agent_lock = asyncio.Lock()

def event_callback(session_id: str, event_data: Dict[str, Any]):
    """
    Helper function to put events into the correct session queue.
    Emulates the structure expected by the frontend.
    """
    q = event_queues.get(session_id)
    if q:
        q.put(json.dumps(event_data))

async def run_orchestration_with_streaming(user_input: str, session_id: str):
    """
    Runs the agent's streaming response and sends events to the SSE queue.
    """
    if not global_agent:
        event_callback(session_id, {
            "nodeId": "error",
            "status": "failed",
            "details": "Agent not initialized",
            "raw": {}
        })
        return

    # Emulate analysis phase
    event_callback(session_id, {
        "nodeId": "analyze",
        "status": "started",
        "details": "Analyzing user query...",
        "raw": {"query": user_input}
    })

    # Emulate tool calling phase
    event_callback(session_id, {
        "nodeId": "call_tools",
        "status": "started",
        "details": "Calling weather tools...",
        "raw": {"query": user_input}
    })

    # Simulate tool calling delay
    await asyncio.sleep(0.5)

    # Stream the agent's response
    full_response = ""
    try:
        async with global_agent.run_stream(user_input) as result:
            async for chunk in result.stream_text(delta=True):
                full_response += chunk
                # Optionally send intermediate chunks if needed
                # event_callback(session_id, {
                #     "nodeId": "respond",
                #     "status": "streaming",
                #     "details": chunk,
                #     "raw": {"chunk": chunk}
                # })

        # Send completion events
        event_callback(session_id, {
            "nodeId": "call_tools",
            "status": "completed",
            "details": "Weather tools called successfully.",
            "raw": {}
        })

        event_callback(session_id, {
            "nodeId": "respond",
            "status": "completed",
            "details": full_response,
            "raw": {"response": full_response}
        })

    except Exception as e:
        event_callback(session_id, {
            "nodeId": "error",
            "status": "failed",
            "details": f"Error during orchestration: {str(e)}",
            "raw": {"error": str(e)}
        })


@app.post("/api/agent/execute")
async def execute_workflow(request: Request):
    data = await request.json()
    user_input = data.get("input", "")
    session_id = data.get("session_id", "default")

    if not global_agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=500)

    # Create a queue for this session's events
    q = queue.Queue()
    event_queues[session_id] = q

    # Run orchestration in background so SSE can stream events
    asyncio.create_task(run_orchestration_with_streaming(user_input, session_id))
    return JSONResponse({"status": "started", "session_id": session_id})

@app.get("/api/agent/events")
async def stream_events(session_id: str = "default"):
    q = event_queues.get(session_id)
    if not q:
        # No events for this session yet
        def empty_stream():
            yield "event: end\n {}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    def event_stream():
        while True:
            try:
                event = q.get(timeout=60)
                yield f"data: {event}\n\n"
                # Check for the final completion event to close the stream
                if '"status": "completed"' in event and '"nodeId": "respond"' in event:
                    break
            except queue.Empty:
                break
        # Optionally clear the queue after stream ends
        # event_queues.pop(session_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/api/agent")
async def chat_endpoint(request: Request):
    """Direct chat endpoint for immediate responses (used by chat interface)"""
    data = await request.json()
    user_input = data.get("input", data.get("message", ""))

    if not global_agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=500)

    # Acquire lock to ensure thread-safe access to the agent
    async with agent_lock:
        try:
            # Run the agent synchronously to get the final response
            result = await global_agent.run(user_input)
            
            # Access the output correctly from AgentRunResult
            # The primary output is usually in result.data or result.return_value
            if hasattr(result, 'data'):
                final_response_data = result.data
            elif hasattr(result, 'return_value'):
                final_response_data = result.return_value
            elif hasattr(result, 'output'):
                 # Some versions might use 'output'
                final_response_data = result.output
            else:
                # Fallback to string representation of the result object
                final_response_data = str(result)

            # The final_response_data might be a string or a structured object
            # If it's a structured object, convert it to a string for the response
            if isinstance(final_response_data, (dict, list)):
                final_response_text = json.dumps(final_response_data)
            else:
                final_response_text = str(final_response_data)

            return JSONResponse({"response": final_response_text})
        except Exception as e:
            # Log the error for debugging
            import traceback
            traceback.print_exc()
            return JSONResponse({"response": f"Error processing request: {str(e)}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
