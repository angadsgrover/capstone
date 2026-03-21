# Development Guide

This guide covers local development setup, running services individually, and testing workflows.

## Prerequisites

- **Python 3.12+** (3.14 optional; 3.12 recommended for stability)
- **Node.js 22+**
- **PostgreSQL 16** (for local DB; optional if using Docker)
- **Git**

## Local Setup (Non-Docker)

For iterative development without Docker, run each service in its own terminal.

### 1. Backend Setup

```bash
cd agent

# Create + activate venv
python3.12 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# or: .venv\Scripts\activate  # Windows

# Install deps
pip install -r requirements.txt

# Copy + edit .env
cp .env.example .env
# Fill in: LLM_API_KEY, MODEL_CHOICE, BASE_URL, POSTGRES_PASSWORD

# Optional: local PostgreSQL
# macOS: brew install postgresql
# Then: brew services start postgresql
# Create DB: createdb -U postgres capstone
# Update .env: POSTGRES_DSN=postgresql://postgres@localhost:5432/capstone
```

### 2. Start MCP Servers (in separate terminals)

Each MCP server runs as an SSE endpoint, making them easy to test independently.

**Aviation Weather MCP** (port 8001):
```bash
cd aviation-weather-mcp-python
source ../.venv/bin/activate  # use agent venv

# Create local venv if not already done
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# Start server in SSE mode
TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8001 \
  python -m aviation_weather_mcp_server
# Output: "Listening on http://0.0.0.0:8001"
```

**HK Climate MCP** (port 8002):
```bash
cd hk-climate-mcp-server-python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8002 \
  python -m hk_climate_mcp_server
```

**ADS-B MCP** (port 8003):
```bash
cd adsb_mcp
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8003 python server.py --sse --host 0.0.0.0 --port 8003
```

### 3. Initialize Database (First Time Only)

```bash
# Local PostgreSQL
psql -U postgres capstone < infra/init.sql

# or via Docker (if running postgres in Docker)
docker compose exec postgres psql -U capstone -f /docker-entrypoint-initdb.d/init.sql
```

### 4. Start FastAPI Server

```bash
cd agent
source .venv/bin/activate

# Lifespan will:
# - Connect to PostgreSQL (if POSTGRES_DSN set)
# - Initialize mem0 (if POSTGRES_DSN set)
# - Start APScheduler ingestion (METAR/TAF polling)
# - Launch MCP clients (connects to port 8001/8002/8003)
# - Compile LangGraph

python server.py
# Output: "Listening on http://0.0.0.0:8000"
```

### 5. Start Frontend Dev Server

```bash
cd frontend-app

npm install  # if not done
npm run dev
# Output: "Local: http://localhost:5173"
```

### Access Points

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:5173 | Vite dev server (hot reload) |
| FastAPI | http://localhost:8000/docs | Swagger UI (test endpoints) |
| PostgreSQL adminer | — | Use `psql` CLI or PgAdmin locally |

---

## Run Without Docker From a New Drive (Same Machine)

Use this when you want to move the project to a larger internal/external drive and run everything natively.

### Fast path (single command)

```bash
bash ./start-local-new-drive.sh
```

Optional flags pass through to `start.sh`:

```bash
bash ./start-local-new-drive.sh --no-frontend
bash ./start-local-new-drive.sh --check
bash ./start-local-new-drive.sh --test
```

This script creates a shared root `.venv`, installs all Python/frontend dependencies once, and starts the local stack.
It requires Python 3.12 or 3.13 (3.14 may fail on dependency constraints).

### 1. Clone on the new drive

```bash
cd /Volumes/YourNewDrive
git clone <your-repo-url> capstone
cd capstone
cp .env.example .env
```

### 2. Install frontend dependencies

```bash
cd frontend-app
npm ci
cd ..
```

### 3. Create one shared Python virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 4. Install Python dependencies once in shared env

```bash
pip install -e aviation-weather-mcp-python
pip install -e hk-climate-mcp-server-python
pip install -e adsb_mcp
pip install -r agent/requirements.txt
deactivate
```

### 5. Configure `.env` for local (non-Docker) runtime

Set these values in root `.env`:

```bash
LLM_API_KEY=sk-...
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b

# Local PostgreSQL DSN (update user/password/port to your local setup)
POSTGRES_DSN=postgresql://capstone:<password>@localhost:5432/capstone

# Optional long-term graph memory
COGNEE_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<neo4j-password>
```

### 6. Start services without Docker

Recommended (single command):

```bash
./start.sh
```

Or API-only:

```bash
./start.sh --no-frontend
```

### 7. Validate

```bash
curl -s http://localhost:8000/docs > /dev/null && echo "API OK"
curl -s http://localhost:5173 > /dev/null && echo "Frontend OK"
```

### 8. Common new-drive issues

- If external drive path contains spaces, quote paths in commands.
- If venv Python points to old path, recreate root `.venv` on the new drive.
- On macOS, allow terminal access to external volumes if permission prompts appear.

---

## Testing

### Unit Tests (Local)

```bash
cd agent

# Test router classification
python -m pytest orchestrator_test.py::test_router_classification -v

# Test all in tools/
python -m pytest tools/ -v --tb=short

# Test conversation persistence
python -m pytest db_test.py -v
```

### Integration Tests (Endpoints)

#### Test 1: Simple Query (Non-Streaming)

```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello, what can you help me with?",
    "session_id": "dev-test-1"
  }' | jq .
```

Expected response:
```json
{
  "response": "I can help you with aviation weather..."
}
```

#### Test 2: Weather Query (Routed to Aviation Specialist)

```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What is the METAR at Heathrow?",
    "session_id": "dev-test-2"
  }' | jq .
```

Should route to `aviation_weather` specialist and call MCP tools.

#### Test 3: Streaming Response

```bash
curl -N "http://localhost:8000/api/agent/stream?input=Weather%20at%20VHHH&session_id=dev-test-3"
```

Output (SSE format):
```
data: {"chunk":"The"}
data: {"chunk":" current"}
data: {"tool_start":"get_metar","tool_input":"icao=VHHH"}
data: {"tool_end":"get_metar"}
...
event: end
data: {}
```

#### Test 4: Workflow Events (Rich Trace)

Terminal 1 — Trigger execution:
```bash
curl -X POST http://localhost:8000/api/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"input": "Track CX680", "session_id": "workflow-test"}' | jq .
```

Terminal 2 — Subscribe to events:
```bash
curl -N "http://localhost:8000/api/agent/events?session_id=workflow-test" | jq .
```

Sample events flowing:
```json
{"nodeId":"router","event_type":"node","status":"started",...}
{"nodeId":"router","event_type":"routing_decision","route":"aircraft",...}
{"nodeId":"aircraft","event_type":"reasoning","step":1,"label":"Step 1: Planning",...}
```

#### Test 5: Conversation Persistence

Query 1:
```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "I work for CX.",
    "session_id": "memory-test"
  }' | jq .
```

Query 2 (should remember CX = Cathay Pacific):
```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What flights are operating?",
    "session_id": "memory-test"
  }' | jq .
```

Check database:
```bash
psql -U capstone -c "SELECT role, content FROM conversations WHERE session_id = 'memory-test' ORDER BY created_at;"
```

#### Test 6: RAG Search

```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Find similar weather to today at VHHH.",
    "session_id": "rag-test"
  }' | jq .
```

If embeddings exist, `rag_search` tool is called automatically.

---

## Debugging

### Enable Verbose Logging

```bash
# In agent/server.py or any module:
import logging
logging.basicConfig(level=logging.DEBUG)

# Run with Python debug output
python -u server.py  # unbuffered output
```

### Inspect LangGraph State

```python
# In orchestrator.py test or CLI:
from orchestrator import init_graph
from langchain_core.messages import HumanMessage

async def debug_flow():
    graph, client, _ = await init_graph()
    config = {"configurable": {"thread_id": "debug-1"}}

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Weather at EGLL")]},
        config=config
    )

    print("Final messages:", result["messages"])
    print("Route:", result.get("route"))

asyncio.run(debug_flow())
```

### Check MCP Tool Availability

```bash
# Query MCP server directly (if running on port 8001):
curl http://localhost:8001/sse -H "Content-Type: application/x-www-form-urlencoded" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .
```

### PostgreSQL Queries

```bash
# Connect
psql -U capstone

# View conversations
SELECT session_id, role, substring(content, 1, 50) as preview, created_at
FROM conversations
ORDER BY created_at DESC
LIMIT 10;

# View embeddings count
SELECT source_type, COUNT(*) as count
FROM embeddings
GROUP BY source_type;

# Check METAR history
SELECT icao, obs_time, flight_cat, raw_text
FROM metar_history
ORDER BY obs_time DESC
LIMIT 5;

# Check if AGE is installed
SELECT * FROM pg_available_extensions WHERE name = 'age';

# Test Cypher query (if AGE installed)
SELECT * FROM cypher('aviation', 'MATCH (n:Airport) RETURN n LIMIT 1') AS (v agtype);
```

---

## Common Issues

### "Orchestrator not found" Error

**Symptom**: `ModuleNotFoundError: No module named 'orchestrator'`

**Solution**: Ensure you're running from `agent/` directory:
```bash
cd agent
python server.py
```

### MCP Servers Not Connecting

**Symptom**: `ConnectionError: Failed to connect to http://localhost:800X`

**Cause**: One of the MCP server processes isn't running.

**Solution**:
```bash
# In separate terminals, ensure all 3 are running:
# Terminal 1:
TRANSPORT_MODE=sse PORT=8001 python -m aviation_weather_mcp_server

# Terminal 2:
TRANSPORT_MODE=sse PORT=8002 python -m hk_climate_mcp_server

# Terminal 3:
TRANSPORT_MODE=sse PORT=8003 python adsb_mcp/server.py --sse --port 8003

# Then check connectivity:
curl http://localhost:8001/sse  # should hang (waiting for SSE request)
```

### PostgreSQL Connection Fails

**Symptom**: `asyncpg.PostgresError: <exception details>`

**Solution**:
```bash
# Check if postgres is running
ps aux | grep postgres

# Test connection
psql -U capstone -h localhost

# If not running (macOS):
brew services start postgresql

# Or verify POSTGRES_DSN in .env
echo $POSTGRES_DSN  # should be: postgresql://capstone:password@localhost:5432/capstone
```

### mem0 Initialization Fails

**Symptom**: `mem0: init failed` in logs, memory features disabled

**Cause**: POSTGRES_DSN not set or embedding provider unreachable.

**Solution**:
```bash
# Ensure POSTGRES_DSN is set
grep POSTGRES_DSN .env

# Test embedding provider
python -c "
import openai
client = openai.OpenAI(api_key='your-key', base_url='https://api.openai.com/v1')
resp = client.embeddings.create(input='test', model='text-embedding-3-small')
print('Embedding works:', len(resp.data[0].embedding))
"
```

### Scheduler Not Running

**Symptom**: No METAR/TAF entries appearing in database

**Cause**: Database not available or scheduler not initialized.

**Solution**:
```bash
# Check logs for scheduler startup
grep "scheduler started" agent.log  # if redirected

# Manually trigger ingestion (for testing):
python -c "
import asyncio
from ingestion.metar_ingestor import ingest_metar
from db import Database

async def test():
    db = Database()
    await db.connect()
    n = await ingest_metar(db)
    print(f'Ingested {n} METARs')
    await db.close()

asyncio.run(test())
"
```

---

## Performance Profiling

### Profile Router Speed

```python
import time
from orchestrator import get_chat_model
from langchain_core.messages import SystemMessage, HumanMessage

router_llm = get_chat_model(streaming=False, max_tokens=16)

queries = [
    "What's the weather at Heathrow?",
    "HK typhoon warnings?",
    "Track CX680",
    "General question about aviation"
]

for q in queries:
    start = time.time()
    resp = router_llm.invoke([
        SystemMessage(content="...ROUTER_PROMPT..."),
        HumanMessage(content=q),
    ])
    elapsed = time.time() - start
    print(f"{q[:30]:30} → {resp.content:20} ({elapsed:.2f}s)")
```

### Profile Vector Search

```python
import asyncio
import time
from ingestion.embedder import embed_text
from db import Database

async def profile_rag():
    db = Database()
    await db.connect()

    query = "severe weather at international airports"
    start = time.time()
    embedding = await embed_text(query)
    embed_time = time.time() - start
    print(f"Embedding: {embed_time:.2f}s")

    start = time.time()
    results = await db.rag_search(embedding, limit=10)
    search_time = time.time() - start
    print(f"Search: {search_time:.2f}s, {len(results)} results")

    await db.close()

asyncio.run(profile_rag())
```

---

## Frontend Development

### Hot Reload (Vite)

```bash
cd frontend-app
npm run dev

# Any change to .tsx files triggers rebuild + browser refresh
```

### Types & APIs

The frontend communicates with the backend via:

| File | Usage |
|------|-------|
| `src/shared/services/agentService.ts` | POST /api/agent, execute, stream |
| `src/shared/types/agent.ts` | Message, StreamEvent, AgentRequest types |
| `src/shared/state/chatStore.ts` | Zustand store (messages, sessions) |

To add a new endpoint:

1. Define types in `src/shared/types/agent.ts`
2. Add service method in `src/shared/services/agentService.ts`
3. Use in component via hook or direct import

### Building

```bash
cd frontend-app

# Production build
npm run build

# Output: dist/ folder
# Preview build: npm run preview
```

---

## Docker vs Local

| Aspect | Local | Docker |
|--------|-------|--------|
| Startup | ~30s (init graph + DB) | ~60s (build + services) |
| Changes | Hot reload (Vite, uvicorn) | Requires rebuild |
| Debug | Full Python traceback | Check logs |
| PostgreSQL | Local/Homebrew | Container (volume persist) |
| Scaling | Single machine | Multiple containers, orchestration |

**Recommendation**: Use **local** for development (faster iteration), **Docker** for testing deployment scenarios.

---

## Tips & Tricks

### 1. Speed Up Router

Reduce `max_tokens=16` further or use keyword-only fallback:
```python
# In orchestrator.py
router_llm = get_chat_model(streaming=False, max_tokens=8)
```

### 2. Test Specialist Directly

```python
from orchestrator import get_chat_model
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

@tool
def dummy_tool(x: str) -> str:
    return f"Result: {x}"

llm = get_chat_model()
agent = create_react_agent(llm, tools=[dummy_tool])
result = agent.invoke({"messages": [HumanMessage(content="Use tool with hello")]})
print(result["messages"][-1].content)
```

### 3. Batch Test Multiple Queries

```bash
# Create test_queries.jsonl
{"input": "Weather at EGLL", "session_id": "test-1"}
{"input": "HK weather", "session_id": "test-2"}
{"input": "Track CX680", "session_id": "test-3"}

# Run all
cat test_queries.jsonl | while read line; do
  curl -X POST http://localhost:8000/api/agent \
    -H "Content-Type: application/json" \
    -d "$line" | jq '.response | .[0:80]'
done
```

### 4. Clear Session Data

```bash
# Postgres
psql -U capstone -c "TRUNCATE conversations; TRUNCATE embeddings;"

# mem0 (if available)
# Currently no direct delete; would require mem0 API enhancement
```

---

## Next Steps

- **Modify prompts**: Edit `AVIATION_PROMPT`, etc. in `orchestrator.py`
- **Add tools**: Create new MCP server in separate directory; add to `mcp_config.json`
- **Custom memory**: Adjust mem0 config in `agent/memory.py`
- **Performance**: Profile with `cProfile` or async debugger; see Performance Tuning in README.md

---

**Happy coding!** 🚀
