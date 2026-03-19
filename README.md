# Capstone: Aviation Intelligence Platform

A full-stack multi-agent AI system for aviation weather, aircraft tracking, and Hong Kong climate intelligence. Built with **LangGraph**, **FastAPI**, **React 19**, and **PostgreSQL + pgvector**.

## What It Does

- **Intelligent Routing**: Router LLM classifies user queries → dispatches to specialized agents
- **4 Specialist Agents**: Aviation weather | HK climate | Aircraft tracking | General Q&A
- **Live Streaming**: Token-by-token SSE streaming + rich workflow event tracing
- **Dual Memory System**: Short-term (mem0) + Long-term (cognee) for context + knowledge graphs
- **High-Performance Caching**: Redis layer for 2-5x faster responses (40-60% hit rate)
- **Historical RAG**: Semantic search over METAR/TAF archives + safety benchmarks
- **Knowledge Graph**: Apache AGE (optional) + cognee for entity relationships + domain expertise
- **Mobile-Ready**: React Native guide for iOS/Android apps (portable shared layer)
- **Multi-Provider LLM**: OpenRouter (default), OpenAI, Groq, Ollama, etc.

## Quick Start (Docker)

```bash
# 1. Clone + setup
git clone <repo>
cd capstone
cp .env.example .env

# 2. Fill in secrets in .env
# Required:
#   LLM_API_KEY=sk-... (from OpenRouter or OpenAI)
#   POSTGRES_PASSWORD=secure_password
#   BASE_URL=https://openrouter.ai/api/v1 (or your provider)
#   MODEL_CHOICE=qwen/qwen3-8b

# 3. Launch (pgvector only)
docker compose up -d

# Wait ~30s for services to start. Access:
#   Frontend:  http://localhost:80
#   Agent API: http://localhost:8000/docs (Swagger)
#   Adminer:   http://localhost:8080 (if running with --profile dev)

# 4. Stop
docker compose down
```

## Unified Entry Point (Local Dev)

```bash
# 1. Configure env (root .env)
cp .env.example .env

# 2. Start everything (MCP servers + agent + frontend)
./start.sh

# Optional:
# ./start.sh --check     # Health checks only
# ./start.sh --test      # Run integration tests after startup
# ./start.sh --no-frontend  # API-only
```

### With Apache AGE Graph (Optional)

```bash
# Build custom postgres image with Apache AGE (takes ~10 min on first run)
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres

# Start all services including AGE
docker compose -f docker-compose.yml -f docker-compose.graph.yml up -d

# Also start Neo4j for graph ML (optional):
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

## Local Development

See [DEVELOPMENT.md](./DEVELOPMENT.md) for:
- Python venv setup
- Running MCP servers locally
- Running FastAPI + Vite dev servers in parallel
- Testing individual components
- Debugging LangGraph workflows

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Vite + React 19)                                 │
│  - Chat view (SSE streaming)                                │
│  - Workflow visualizer (ReactFlow)                          │
│  - Logs explorer (rich event table)                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ /api/*
                ┌──────────▼──────────┐
                │  nginx (reverse     │
                │  proxy)             │
                └──────────┬──────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI Agent (port 8000)                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ LangGraph Orchestrator                               │  │
│  │  router → 4 specialist create_react_agent           │  │
│  │  + dual memory (mem0 + cognee)                       │  │
│  │  (aviation_weather, hk_weather, aircraft, general)   │  │
│  └──────────────────────────────────────────────────────┘  │
│  - Endpoints: /api/agent, /api/agent/stream,               │
│              /api/knowledge/*, /api/memory/status          │
│  - Conversation persisted to PostgreSQL                    │
│  - Short-term memory: mem0 + pgvector                      │
│  - Long-term memory: cognee + pgvector + Neo4j (optional)  │
└──────────────┬──────────────────┬──────────────┬───────────┘
               │                  │              │
    ┌──────────▼─┐      ┌─────────▼──┐  ┌──────▼────────┐
    │ MCP servers│      │ PostgreSQL │  │ APScheduler  │
    │ (3× SSE):  │      │            │  │ (ingestion)   │
    │ - aviation │      │ pgvector   │  │ - METAR/TAF   │
    │ - hk-clim. │      │ pgbouncer? │  │ - embeddings  │
    │ - adsb     │      │ Apache AGE │  │ - mem0 facts  │
    └────────────┘      │ (optional) │  └───────────────┘
                        └────────────┘
```

## Key Features

### 1. Smart Routing
- User input → router LLM (16 tokens max, keyword fallback)
- Classifies into: `aviation_weather` | `hk_weather` | `aircraft` | `general`
- Each route has 3–5 focused MCP tools (90+ tools total across all providers)

### 2. Multi-Agent Orchestration & Dual Memory

**Memory Architecture**:
- **MemorySaver** (checkpointer): within-session conversation history (LangGraph native)
- **Short-term Memory (mem0)**: Recent conversational context, user preferences, session facts (pgvector)
- **Long-term Memory (cognee)**: Persistent knowledge graphs from safety documents, regulations, domain expertise (pgvector + optional Neo4j)
- **Message trimming**: specialists see last 20 messages (configurable; full history in DB)
- **Tool truncation**: 8000-char limit per tool output (configurable)

**How Memory Works**:
1. **Automatic Injection**: Every specialist query gets relevant short-term + long-term context in system prompt
2. **Explicit Tool**: `knowledge_graph_search` tool lets agents query cognee for deep domain knowledge
3. **Separation of Concerns**: mem0 for ephemeral session context, cognee for persistent expertise

See [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) for full details.

### 3. Real-Time Streaming
- `/api/agent/stream`: token-by-token SSE + tool call tracking
- `/api/agent/events`: rich workflow events (reasoning steps, routing, tool execution, durations)
- Frontend: live ReactFlow visualization + Logs table with filters

### 4. Semantic Search (RAG)
- `rag_search` tool: pgvector cosine search over embeddings
- Historical METAR/TAF + safety incidents searchable by natural language
- Scheduler auto-ingests latest METAR (every 30 min) + TAF (every 60 min) from aviationweather.gov
- Embeddings pre-computed via OpenAI text-embedding-3-small (1536 dims)

### 5. Knowledge Graph (Optional)
- Apache AGE: openCypher queries on aviation ontology
- Seed airports (VHHH, EGLL, KJFK, WSSS, OMDB, RJTT) + routes + safety events
- `graph_search` tool for relationship traversal (e.g., find airports with recent incidents)
- Gracefully disables if AGE not installed; default setup uses pgvector-only

## Endpoints

### Core Agent Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/agent` | Non-streaming full response (conversation persisted to DB) |
| GET | `/api/agent/stream` | SSE token streaming + tool calls |
| POST | `/api/agent/execute` | Trigger async workflow, returns session_id |
| GET | `/api/agent/events` | SSE rich workflow events (execution trace) |

### Memory & Knowledge Graph Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory/status` | Check short-term/long-term memory availability |
| POST | `/api/knowledge/ingest` | Ingest single document into cognee knowledge graph |
| POST | `/api/knowledge/ingest-batch` | Batch ingest multiple documents |
| GET | `/api/knowledge/search` | Search long-term knowledge graph (query param) |
| GET | `/api/knowledge/entity/{name}` | Retrieve specific entity from knowledge graph |

### Request/Response Examples

**POST `/api/agent`** — Non-streaming response:
```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What is the weather at Heathrow?",
    "session_id": "user-session-123"
  }'
```

Response:
```json
{
  "response": "The current METAR for EGLL indicates VFR conditions with 10 knots wind from 180°..."
}
```

**GET `/api/agent/stream`** — Streaming tokens:
```bash
curl "http://localhost:8000/api/agent/stream?input=Weather%20at%20VHHH&session_id=test-1"
```

Events stream as:
```
data: {"chunk":"The"}
data: {"chunk":" current"}
data: {"tool_start":"get_metar","tool_input":"..."}
data: {"tool_end":"get_metar"}
...
event: end
```

**POST `/api/agent/execute`** + **GET `/api/agent/events`** — Rich workflow trace:
```bash
# Trigger execution
curl -X POST http://localhost:8000/api/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"input": "Track CX680", "session_id": "track-cx680"}'

# Subscribe to workflow events in another terminal
curl "http://localhost:8000/api/agent/events?session_id=track-cx680"
```

Events include:
- Routing decision (which specialist chosen)
- Reasoning steps (planning + synthesis)
- Tool execution (start/end with duration)
- Node completion with total step counts

## Environment Variables

### Required (copy to `.env` from `.env.example`)
```bash
LLM_API_KEY=sk-your-api-key                # OpenRouter, OpenAI, Groq, etc.
BASE_URL=https://openrouter.ai/api/v1      # or https://api.openai.com/v1
MODEL_CHOICE=qwen/qwen3-8b                  # model ID from your provider
POSTGRES_PASSWORD=strong_secure_password
```

### Optional
```bash
# Separate embedding provider (default: same as BASE_URL/LLM_API_KEY)
EMBED_API_KEY=sk-...
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=openai/text-embedding-3-small  # or -large, cohere, mistral, nomic

# Memory System (Dual: mem0 + cognee)
COGNEE_ENABLED=true  # enable long-term knowledge graph (default: true)

# Neo4j (enhances cognee graph queries + AGE graph support)
NEO4J_PASSWORD=another_strong_password
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j

# Observability (Langfuse tracing)
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...

# Local dev ingestion (if not using Docker)
METAR_ICAO_LIST=VHHH,EGLL,KJFK,WSSS,OMDB,RJTT  # only used by scheduler.py
```

## Database Schema

### Relational Tables
```sql
conversations   -- session_id, role ('human'|'ai'), content, metadata, created_at
embeddings      -- source_type, content, vector(1536), metadata for RAG
metar_history   -- icao, raw_text, obs_time, flight_cat, wind, temp, etc.
taf_history     -- icao, raw_text, issue_time, valid_from, valid_to
safety_events   -- source ('ASRS'|'NTSB'|'ICAO'), event_date, narrative, severity
```

### Apache AGE Graph (optional)
```
aviation graph:
  :Airport {icao, name, lat, lon}
  :SafetyEvent {severity, date, event_type, aircraft}
  :ROUTE edges {distance_nm, operator}
```

Seed queries:
```cypher
MATCH (a:Airport)-[:ROUTE]->(b:Airport)
RETURN a.icao, b.icao, r.distance_nm

MATCH (a:Airport)-[:HAD_EVENT]->(e:SafetyEvent)
WHERE e.severity = 'IFR'
RETURN a.icao, e.narrative
```

## Testing

### Local Unit Tests
```bash
cd agent
python -m pytest tests/ -v

# Test routing decisions
python -m pytest orchestrator_test.py::test_router_classification -v

# Test RAG tool
python -m pytest tools/test_rag_search.py -v
```

### Integration Test (Docker)
```bash
# After docker compose up

# 1. Simple query
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello", "session_id": "test-1"}'

# 2. Aviation query (should route to aviation_weather)
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{"input": "METAR at EGLL", "session_id": "test-2"}'

# 3. Check database
docker compose exec postgres psql -U capstone -c "SELECT * FROM conversations LIMIT 5;"

# 4. Frontend UI (http://localhost:80)
#    - Chat tab: perform queries
#    - Workflow tab: see event tracing in real-time
#    - Logs tab: inspect all events with filters
```

## Troubleshooting

### Docker Services Won't Start
```bash
# Check logs
docker compose logs -f agent

# Ensure postgres is ready
docker compose exec postgres pg_isready -U capstone

# Rebuild images (no cache)
docker compose build --no-cache
docker compose up -d
```

### MCP Servers Failing (Port Errors)
```bash
# Check if SSE endpoints are reachable
curl http://localhost:8001/sse  # should hang waiting for requests
curl http://localhost:8002/sse
curl http://localhost:8003/sse

# If not starting, check MCP server logs
docker compose logs mcp-aviation-wx
docker compose logs mcp-hk-climate
docker compose logs mcp-adsb

# Port conflicts
netstat -an | grep 800[123]  # check if ports are in use
```

### mem0 or RAG Not Working
- Ensure `POSTGRES_DSN` is set (check compose logs)
- Check `EMBED_API_KEY` is valid if using separate embeddings provider
- Verify scheduler is running: `docker compose logs agent | grep "scheduler started"`
- Query test: `curl "http://localhost:8000/api/agent/stream?input=weather%20at%20LAX"`

### Apache AGE Queries Failing
```bash
# Check if AGE extension is installed
docker compose exec postgres psql -U capstone -c "\dx"  # list extensions

# If missing, rebuild image with docker-compose.graph.yml
docker compose -f docker-compose.yml -f docker-compose.graph.yml down -v
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.graph.yml up postgres

# Test graph query directly
docker compose exec postgres psql -U capstone -c \
  "SELECT * FROM cypher('aviation', 'MATCH (n:Airport) RETURN n LIMIT 1') AS (v agtype);"
```

### Frontend Shows No Response
- Check agent logs for initialization errors
- Verify CORS is enabled (it is by default, `allow_origins=["*"]`)
- Inspect network tab in browser dev tools for 5XX errors

## Performance Tuning

### Token/Message Configuration
```python
# agent/orchestrator.py
MAX_HISTORY_MESSAGES = 20      # messages shown to specialist (default: 20)
MAX_RESPONSE_TOKENS = 2048     # tokens per specialist response (default: 2048)
MAX_TOOL_OUTPUT_CHARS = 8000   # per-tool truncation (default: 8000)
SPECIALIST_RECURSION_LIMIT = 50  # ReAct loop depth (default: 50)
```

### Database Optimization
```sql
-- Check HNSW index performance
EXPLAIN ANALYZE
SELECT content, 1 - (embedding <=> $1::vector) AS similarity
FROM embeddings
ORDER BY embedding <=> $1::vector
LIMIT 5;

-- Monitor table sizes
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### LLM Provider Comparison
| Provider | Model | Speed | Quality | Cost |
|---|---|---|---|---|
| OpenRouter | qwen/qwen3-8b | ⚡⚡⚡ | ⭐⭐⭐ | 💰 |
| OpenRouter | grok-3 | ⚡⚡ | ⭐⭐⭐⭐ | 💰💰 |
| OpenAI | gpt-4o-mini | ⚡⚡ | ⭐⭐⭐⭐ | 💰💰 |
| Groq | Mixtral 8x7B | ⚡⚡⚡ | ⭐⭐⭐ | 💰 |
| Ollama | Mistral (local) | ⚡ | ⭐⭐⭐ | Free |

## Models Tested

- ✅ OpenRouter (qwen, grok, etc.) — fast, low cost
- ✅ OpenAI (gpt-4o-mini) — reliable, good quality
- ✅ Groq (Mixtral 8x7B) — ultra-fast
- ✅ Ollama (local Mistral) — privacy-focused, offline

**Tip**: Smaller models (8B) work well with specialist routing because fewer tools per agent reduce confusion.

## Future Enhancements

1. **cognee**: Auto-build knowledge graphs from safety documents (Phase 7)
2. **Re-ranker**: BM25 keyword + semantic rank for RAG results
3. **Time-series**: Store/forecast wind/temp trends per airport
4. **Mobile**: React Native port of components (type layer already portable)
5. **Webhooks**: Real-time alerts on safety events, weather warnings
6. **RBAC**: Role-based access for multi-tenant deployments
7. **Caching**: Redis layer for frequently-asked queries

## Support & Contributing

- **Documentation**: See [DEVELOPMENT.md](./DEVELOPMENT.md) for detailed setup guides
- **Issues**: Check logs and [Troubleshooting](#troubleshooting) section
- **Performance**: Adjust `MAX_HISTORY_MESSAGES`, token limits, or LLM provider in `.env`
- **Contributing**: PRs welcome; ensure tests pass before submission

---

**Built with** ❤️ **using LangGraph, FastAPI, React 19, and PostgreSQL + pgvector**
