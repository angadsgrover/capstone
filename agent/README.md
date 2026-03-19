# Agent Service (LangGraph Orchestrator)

This service is the backend orchestration layer for the Aviation Intelligence Platform. It routes requests to specialist agents, streams execution telemetry, and integrates memory, RAG, and MCP tools.

## Current Architecture

- Runtime: FastAPI + LangGraph + LangChain ReAct agents
- Router categories: `aviation_weather`, `hk_weather`, `aircraft`, `planning`, `general`
- Specialist execution: dedicated `create_react_agent` instances with focused tools
- Planning mode (Phase 15): plan-and-execute graph with explicit plan metadata and execution traces
- Memory: MemorySaver checkpointer + mem0 (short-term) + cognee (long-term)
- Retrieval (Phase 9): hybrid RAG (`pgvector` + BM25 reranking)
- Caching: Redis for hot query paths

## Phase 9 Hybrid Retrieval

`rag_search` now supports hybrid scoring for better exact-match recall (ICAO codes, callsigns, flight IDs) while keeping latency bounded.

Execution flow:

1. Vector over-fetch from `embeddings` (bounded)
2. BM25 scoring on candidate set
3. Normalized weighted blend
4. Top-k response

Tuning via env vars:

- `RAG_HYBRID_VECTOR_WEIGHT` (default `0.7`)
- `RAG_HYBRID_BM25_WEIGHT` (default `0.3`)
- `RAG_HYBRID_OVERFETCH_FACTOR` (default `4`)
- `RAG_HYBRID_OVERFETCH_CAP` (default `60`)

Fallback behavior: if BM25 is unavailable, semantic-only ranking is used.

## Phase 15 Multi-Step Planning

For complex requests, routing can select `planning`.

Planning pipeline:

1. `plan` node generates execution steps
2. `execute` node runs each step
3. `synthesize` node composes final answer

Planning metadata surfaced to clients:

- `route`
- `plan`
- `execution_trace`
- streaming events (`plan`, `thinking`, `tool_start`, `tool_end`)

## API Endpoints

Core:

- `POST /api/agent`
- `GET /api/agent/stream`
- `POST /api/agent/execute`
- `GET /api/agent/events`

Knowledge and memory:

- `GET /api/memory/status`
- `POST /api/knowledge/ingest`
- `POST /api/knowledge/ingest-batch`
- `GET /api/knowledge/search`
- `GET /api/knowledge/entity/{entity_name}`

## Local Development

From `agent`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

From repo root:

```bash
./start.sh
```

## Key Files

- `server.py`: FastAPI endpoints and streaming contracts
- `orchestrator.py`: router and specialist graph wiring
- `planning.py`: plan-and-execute graph implementation
- `tools/rag_search.py`: Phase 9 hybrid retrieval
- `memory.py`: mem0 + cognee integration
- `cache.py`: Redis cache manager
- `db.py`: PostgreSQL/pgvector operations

## MCP Integration

Configured through `mcp_client.py` and `mcp_config*.json`:

- Aviation weather MCP server
- HK climate MCP server
- ADS-B MCP server
