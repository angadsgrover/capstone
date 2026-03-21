## Architecture Plan: Dockerization + Vector DB + Long-Term Memory

### 1. Dockerization Strategy

#### The Core Problem
`mcp_config.json` uses hardcoded absolute paths and **stdio subprocess transport**. In Docker each process runs in its own filesystem, so you can't launch subprocesses across containers. The solution is to **switch MCP servers from stdio to SSE/HTTP transport** — FastMCP already supports this natively.

#### Service Layout (docker-compose.yml)

```
┌────────────────────────────────────────────────────────────────┐
│  Docker Network: capstone_net                                   │
│                                                                 │
│  frontend          :80    (nginx serving built Vite dist)      │
│  agent             :8000  (FastAPI + LangGraph + mem0)         │
│  mcp-aviation-wx   :8001  (FastMCP SSE transport)              │
│  mcp-hk-climate    :8002  (FastMCP SSE transport)              │
│  mcp-adsb          :8003  (FastMCP SSE transport)              │
│  postgres          :5432  (pgvector + Apache AGE extensions)   │
│  neo4j             :7474  (optional, if AGE feels limiting)    │
│  adminer           :8080  (lightweight DB admin UI, dev only)  │
└────────────────────────────────────────────────────────────────┘
```

#### Dockerfile per Service

**`agent/Dockerfile`** — Python 3.12 (drop 3.14, docker images too unstable; all dependencies support 3.12)
```
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn
COPY . .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`aviation-weather-mcp-python/Dockerfile`**, **`hk-climate-mcp-server-python/Dockerfile`**, **`adsb_mcp/Dockerfile`** — same pattern, different entry point, expose different port.

**`frontend-app/Dockerfile`** — multi-stage:
```
# Stage 1: build
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json .
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# nginx.conf proxies /api/* → http://agent:8000
```
Nginx acts as reverse proxy so the browser never has mixed-origin issues.

#### MCP transport change (code change in `mcp_client.py`)

Currently `mcp_client.py` uses `stdio_client`. You'd add an SSE mode:

```python
# mcp_config.json in Docker mode:
{
  "mcpServers": {
    "aviation-weather": { "transport": "sse", "url": "http://mcp-aviation-wx:8001/sse" },
    "hk-climate":       { "transport": "sse", "url": "http://mcp-hk-climate:8002/sse" },
    "adsb":             { "transport": "sse", "url": "http://mcp-adsb:8003/sse"        }
  }
}
```

`mcp_client.py` checks the `transport` key; if `"sse"` → use `mcp.client.sse.sse_client(url)` instead of `stdio_client`. Each MCP server's `server.py` switches from `mcp.run()` (stdio) to `mcp.run(transport="sse", port=800X)`.

#### docker-compose.yml skeleton

```yaml
version: "3.9"
services:
  postgres:
    image: pgvector/pgvector:pg16   # includes pgvector
    environment:
      POSTGRES_DB: capstone
      POSTGRES_USER: capstone
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data", "./infra/init.sql:/docker-entrypoint-initdb.d/init.sql"]
    healthcheck: { test: ["CMD", "pg_isready"], interval: 5s }

  mcp-aviation-wx:
    build: ./aviation-weather-mcp-python
    environment: {}           # no secrets needed (external HTTP APIs)
    expose: ["8001"]

  mcp-hk-climate:
    build: ./hk-climate-mcp-server-python
    expose: ["8002"]

  mcp-adsb:
    build: ./adsb_mcp
    expose: ["8003"]

  agent:
    build: ./agent
    environment:
      MCP_CONFIG: /app/mcp_config.docker.json
      POSTGRES_DSN: postgresql://capstone:${POSTGRES_PASSWORD}@postgres:5432/capstone
      LLM_API_KEY: ${LLM_API_KEY}
      MODEL_CHOICE: ${MODEL_CHOICE}
      BASE_URL: ${BASE_URL}
      MEM0_VECTOR_STORE: postgres
      NEO4J_URI: bolt://neo4j:7687   # optional
    depends_on: [postgres, mcp-aviation-wx, mcp-hk-climate, mcp-adsb]

  frontend:
    build: ./frontend-app
    ports: ["80:80"]
    depends_on: [agent]

  neo4j:                            # optional — see §4
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
    ports: ["7474:7474", "7687:7687"]
    volumes: ["neo4jdata:/data"]
    profiles: ["graph"]             # only starts with --profile graph
```

A single `.env` at the repo root provides all secrets. `profiles: ["graph"]` means Neo4j only starts explicitly when you want it — keeps dev setup lightweight.

---

### 2. PostgreSQL + pgvector Schema

```sql
-- infra/init.sql (runs on first container start)

CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector
CREATE EXTENSION IF NOT EXISTS age;             -- Apache AGE graph (see §4)
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Conversation history (replaces MemorySaver's in-memory dict)
CREATE TABLE conversations (
  id          BIGSERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  role        TEXT NOT NULL,          -- 'human' | 'ai' | 'tool'
  content     TEXT NOT NULL,
  metadata    JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON conversations (session_id, created_at);

-- Embeddings for semantic search across all content types
CREATE TABLE embeddings (
  id          BIGSERIAL PRIMARY KEY,
  source_type TEXT NOT NULL,          -- 'metar' | 'taf' | 'safety' | 'conversation'
  source_id   BIGINT,
  content     TEXT NOT NULL,
  embedding   vector(1536),           -- OpenAI / text-embedding-3-small dim
  metadata    JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);

-- Historical METAR archive
CREATE TABLE metar_history (
  id          BIGSERIAL PRIMARY KEY,
  icao        CHAR(4) NOT NULL,
  raw_text    TEXT NOT NULL,
  obs_time    TIMESTAMPTZ NOT NULL,
  flight_cat  TEXT,                   -- VFR/MVFR/IFR/LIFR
  temp_c      REAL, dewpoint_c REAL,
  wind_dir    INT, wind_speed_kt INT, wind_gust_kt INT,
  visibility_sm REAL,
  ceiling_ft  INT,
  altimeter   REAL,
  wx_string   TEXT,
  fetched_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON metar_history (icao, obs_time DESC);

-- Historical TAF archive
CREATE TABLE taf_history (
  id          BIGSERIAL PRIMARY KEY,
  icao        CHAR(4) NOT NULL,
  raw_text    TEXT NOT NULL,
  issue_time  TIMESTAMPTZ NOT NULL,
  valid_from  TIMESTAMPTZ,
  valid_to    TIMESTAMPTZ,
  fetched_at  TIMESTAMPTZ DEFAULT now()
);

-- Safety benchmarks / incident database
CREATE TABLE safety_events (
  id          BIGSERIAL PRIMARY KEY,
  source      TEXT NOT NULL,          -- 'ASRS' | 'NTSB' | 'ICAO' | 'custom'
  event_date  DATE,
  aircraft    TEXT,
  airport_icao CHAR(4),
  event_type  TEXT,                   -- 'incident' | 'accident' | 'bulletin'
  severity    TEXT,
  narrative   TEXT,
  metadata    JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

The `embeddings` table is the central vector index — anything (METAR, TAF, safety narrative, past conversation) gets embedded and stored here, enabling semantic search across all datatypes in one call.

---

### 3. mem0 for Long-Term Memory

**Why mem0 over cognee here**: mem0 is a drop-in enhancement to LangGraph. Its `Memory` class replaces `MemorySaver` checkpointing for *cross-session* memory (what the user told the agent 3 sessions ago). Cognee is better suited as a *knowledge ingestion* layer (see §4).

#### Integration in `orchestrator.py`

```python
from mem0 import Memory

mem0_config = {
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "dbname": "capstone",
            "user": "capstone",
            "password": os.getenv("POSTGRES_PASSWORD"),
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": 5432,
            "embedding_model_dims": 1536,
        }
    },
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": os.getenv("LLM_API_KEY"),
            "openai_base_url": os.getenv("BASE_URL"),
            "model": "text-embedding-3-small",
        }
    }
}
memory = Memory.from_config(mem0_config)
```

In each specialist agent system prompt, you inject the top-k relevant memories retrieved for that `user_id`:

```python
async def build_specialist_prompt(base_prompt: str, session_id: str, query: str) -> str:
    relevant = memory.search(query, user_id=session_id, limit=5)
    if relevant["results"]:
        ctx = "\n".join(r["memory"] for r in relevant["results"])
        return f"{base_prompt}\n\n## Long-term Memory\n{ctx}"
    return base_prompt
```

After each session ends (or after each turn), new facts are extracted and stored:
```python
memory.add(messages, user_id=session_id, metadata={"route": route})
```

**MemorySaver stays** for short-term within-session state. mem0 handles between-session memory. Two layers, different purposes.

---

### 4. Graph DB — Apache AGE vs Neo4j

#### Recommendation: Apache AGE for now, Neo4j behind a profile

**Apache AGE** is a PostgreSQL extension that adds an openCypher graph layer *on top of* your existing Postgres tables — no extra container. You can store airport/route/weather relationships alongside your relational and vector data.

```sql
-- Create the aviation knowledge graph inside Postgres
SELECT create_graph('aviation');

-- Add nodes via Cypher
SELECT * FROM cypher('aviation', $$
  CREATE (:Airport {icao: 'VHHH', name: 'Hong Kong Intl', lat: 22.31, lon: 113.92})
$$) AS (v agtype);

-- Add relationships
SELECT * FROM cypher('aviation', $$
  MATCH (a:Airport {icao: 'VHHH'}), (b:Airport {icao: 'EGLL'})
  CREATE (a)-[:ROUTE {distance_nm: 5990, operator: 'CX'}]->(b)
$$) AS (e agtype);

-- Semantic: airports with IFR incidents in last 30 days
SELECT * FROM cypher('aviation', $$
  MATCH (a:Airport)-[:HAD_EVENT]->(e:SafetyEvent)
  WHERE e.severity = 'IFR' AND e.date > '2026-02-01'
  RETURN a.icao, count(e)
$$) AS (icao agtype, events agtype);
```

**Use Neo4j** (the `--profile graph` service) when you need: graph ML algorithms (community detection, path finding over thousands of nodes), the Bloom visual explorer, or will build a dedicated reasoning layer over aviation ontologies. The switch is transparent to the agent — just change the Cypher driver endpoint.

**cognee** can sit on top of either graph backend and auto-ingest content (documents, conversations) into the graph as an async background task:
```python
import cognee
cognee.config.set_llm_provider("openai")
cognee.config.set_graph_db_provider("neo4j")   # or "kuzu" for embedded
await cognee.add(safety_narrative_text, dataset_name="safety_events")
await cognee.cognify()   # extracts entities + relations → graph
# Now queryable as: await cognee.search("cargo VHHH runway excursion", type="insights")
```

**Recommended stack combining everything:**

```
PostgreSQL (pgvector + Apache AGE)
  ├── vector embeddings     → semantic search (pgvector)
  ├── relational data       → conversations, metar, taf, safety (SQL)
  └── knowledge graph       → airports, routes, events (AGE / Cypher)

mem0                        → long-term user memory (sits on pgvector)
cognee (optional)           → auto-build knowledge graph from documents
LangGraph MemorySaver       → short-term within-session (in-memory, unchanged)
Neo4j (optional profile)    → only if AGE proves limiting
```

---

### 5. Historical METAR/TAF + Safety Benchmarks

#### Data Sources
| Dataset | Source | Format |
|---|---|---|
| Historical METAR/TAF | aviationweather.gov/api/data/metar (CSV/JSON, free) | REST |
| Safety incidents (ASRS) | asrs.arc.nasa.gov/search/database.aspx | CSV bulk |
| NTSB accidents | aviation.ntsb.gov/avdata | MSACCESS/CSV |
| ICAO safety circulars | icao.int (PDF) | PDF → text |
| HK CAD events | cad.gov.hk | HTML/PDF |

#### Ingestion Pipeline

A new `agent/ingestion/` module:

```
agent/ingestion/
  ├── metar_ingestor.py    # polls aviationweather.gov, backfills last N days
  ├── taf_ingestor.py      # same
  ├── safety_ingestor.py   # parses ASRS/NTSB CSV → safety_events table
  ├── embedder.py          # generates embeddings for new rows → embeddings table
  └── scheduler.py         # APScheduler: METAR every 30min, TAF every 1h
```

`scheduler.py` runs as a background task inside the agent container (APScheduler with AsyncIO), or as a separate `ingestion` service in compose. The `embedder.py` uses `text-embedding-3-small` on the RAW text of each METAR/TAF/safety narr and inserts into `embeddings`.

#### RAG Tool for Agents

A new `rag_search` tool exposed to all specialists:

```python
@tool
async def rag_search(query: str, source_type: str = "all", limit: int = 5) -> str:
    """Semantic search over historical METAR/TAF data and safety benchmarks."""
    q_embedding = await embed(query)
    # pgvector cosine search
    rows = await db.fetch("""
        SELECT content, metadata, source_type,
               1 - (embedding <=> $1) AS similarity
        FROM embeddings
        WHERE ($2 = 'all' OR source_type = $2)
        ORDER BY embedding <=> $1
        LIMIT $3
    """, q_embedding, source_type, limit)
    return format_rag_results(rows)
```

This becomes the `5th specialist tool` available to aviation_agent and general_agent — giving them access to historical context without hitting external APIs.

---

### 6. Implementation Phases

| Phase | Scope | Key files changed |
|---|---|---|
| **P1** | Docker infra + MCP SSE transport | `docker-compose.yml`, each MCP `server.py`, `mcp_client.py`, `mcp_config.docker.json` |
| **P2** | PostgreSQL + pgvector + init.sql | `infra/init.sql`, `agent/db.py` (asyncpg) |
| **P3** | mem0 integration | `agent/orchestrator.py` |
| **P4** | Historical data ingestion | `agent/ingestion/*.py` |
| **P5** | RAG tool + embedding pipeline | `agent/tools/rag_search.py`, `agent/ingestion/embedder.py` |
| **P6** | Apache AGE knowledge graph | `infra/init.sql`, `agent/tools/graph_search.py` |
| **P7** | cognee / Neo4j (optional) | `agent/knowledge/cognee_ingestor.py` |

---

### Key Decision Points to Confirm

1. **Python version for Docker**: Recommend dropping 3.14 to **3.12** (stable docker images, all libs support it). Unless there's a hard dependency on 3.14 features.

2. **Embedding model**: `text-embedding-3-small` (1536 dims, cheap) vs local `nomic-embed-text` via Ollama (no API cost, runs in container). Local embedding keeps everything air-gapped if needed.

3. **MCP transport change scope**: Switching from stdio → SSE transport requires a small change to each MCP server's `server.py` (add `transport="sse"` arg to `mcp.run()`) and a `mcp_client.py` update. The existing stdio path stays as a fallback for local dev without Docker.

4. **Apache AGE vs Neo4j**: AGE is zero-extra-infra but less mature. Use `--profile graph` to defer the Neo4j decision until the graph queries get complex enough to justify another service.

5. **cognee vs manual ingestion**: cognee auto-extracts entities/relations from raw text but adds a complex dependency. For MVP, manual ingestion (structured SQL + pgvector) is more predictable. cognee is a good Phase 7 upgrade.