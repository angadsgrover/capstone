# Docker Setup and Operations Guide

This guide is the complete Docker-based setup for this project, including:

- First-time local setup
- Day-to-day operations
- Moving data to a larger drive
- Backup and restore

If you want the full stack (Langfuse + cognee + Neo4j + Apache AGE), jump to section 2.4.

---

## 1. Prerequisites

- Docker Desktop 4.25+ (macOS/Windows) or Docker Engine 24+ (Linux)
- Docker Compose v2 (`docker compose version`)
- Git
- A valid LLM provider key (OpenRouter/OpenAI/etc.)

Check your installation:

```bash
docker --version
docker compose version
```

---

## 2. First-Time Setup

### 2.1 Clone and configure environment

```bash
git clone <your-repo-url>
cd capstone
cp .env.example .env
```

Edit `.env` and set at least:

```bash
LLM_API_KEY=sk-...
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b
POSTGRES_PASSWORD=change_to_a_strong_password
```

### 2.2 Start the core stack

```bash
docker compose up -d
```

Services started:

- `postgres` (pgvector)
- `redis`
- `mcp-aviation-wx`
- `mcp-hk-climate`
- `mcp-adsb`
- `agent`
- `agent-worker` (queue consumer for `/api/agent/execute` when `EXECUTION_MODE=queued`)
- `frontend`

### 2.3 Verify startup

```bash
docker compose ps
docker compose logs -f agent
```

Open:

- Frontend: `http://localhost:80`
- API docs: `http://localhost:8000/docs`

Production hardening env highlights:

```bash
# Security / governance
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
REQUIRE_AUTH_SUBJECT=true
AUTH_VERIFICATION_MODE=jwt
AUTH_REQUIRE_VERIFIED_SUBJECT=true
AUTH_ALLOW_HEADER_FALLBACK=false
JWT_JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
JWT_ISSUER=https://your-idp.example.com/
JWT_AUDIENCE=capstone-agent-api

# Request guards
MAX_REQUEST_BYTES=1048576
MAX_INPUT_CHARS=12000

# Queue + distributed events
EXECUTION_MODE=queued
EVENT_BACKEND=redis
WORKFLOW_QUEUE_KEY=agent:workflow:queue
```

Optional Adminer (DB UI):

```bash
docker compose --profile dev up -d
```

Then open `http://localhost:8080`.

### 2.4 Full Stack Setup (Langfuse + cognee + Neo4j + Apache AGE)

Use this when you want all optional capabilities enabled.

1. Pull latest code:

```bash
git pull
```

1. Configure `.env` with required and optional full-stack variables:

```bash
# Required
LLM_API_KEY=sk-...
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b
POSTGRES_PASSWORD=change_to_a_strong_password

# Enable long-term memory
COGNEE_ENABLED=true

# Neo4j graph store (Docker-internal host)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change_to_a_strong_neo4j_password

# Langfuse tracing (optional but recommended)
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
```

1. Build AGE-enabled Postgres image:

```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres
```

1. Start full stack including graph profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

1. Validate services:

```bash
docker compose ps
docker compose logs --tail=200 agent
docker compose logs --tail=100 neo4j
```

1. Validate memory/tracing endpoints:

```bash
curl -s http://localhost:8000/api/memory/status
curl -s "http://localhost:8000/api/knowledge/search?query=runway"
```

Expected:

- Frontend: `http://localhost:80`
- API docs: `http://localhost:8000/docs`
- Neo4j Browser: `http://localhost:7474`

Notes:

- Langfuse in this stack is configured as external SaaS/self-hosted endpoint via API keys in `agent`; this compose file does not run a Langfuse server container.
- If `NEO4J_PASSWORD` is unset, cognee still runs with vector storage but graph-store enhancement is disabled.

---

## 3. Daily Operations

Start:

```bash
docker compose up -d
```

Stop (keep data):

```bash
docker compose down
```

Stop and remove all persistent data:

```bash
docker compose down -v
```

View logs:

```bash
docker compose logs -f agent
docker compose logs -f frontend
docker compose logs -f postgres
```

Rebuild services after code/dependency changes:

```bash
docker compose build
docker compose up -d
```

Hard rebuild (no layer cache):

```bash
docker compose build --no-cache
docker compose up -d
```

---

## 4. Optional Graph Setup (Apache AGE + Neo4j)

If you want graph features:

```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.graph.yml up -d
```

To also run Neo4j profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

---

## 5. Running on a Larger Drive

You have two valid approaches.

## Option A (Recommended on macOS): Move Docker Desktop data root

This moves all Docker images, layers, containers, and volumes to a larger disk.

1. Open Docker Desktop
1. Go to Settings -> Resources -> Advanced
1. Change Disk image location to your larger drive (for example `/Volumes/ExternalSSD/docker-data`)
1. Apply and restart Docker Desktop

Pros:

- Easiest long-term management
- No compose changes

Cons:

- Moves all Docker workloads, not just this project

## Option B (Per-project): Use bind mounts on an external drive

This keeps only this project's database/cache data on the bigger drive.

### 5.1 Create host directories on larger drive

```bash
mkdir -p /Volumes/ExternalSSD/capstone-data/postgres
mkdir -p /Volumes/ExternalSSD/capstone-data/redis
mkdir -p /Volumes/ExternalSSD/capstone-data/neo4j
```

### 5.2 Create an override compose file

Create `docker-compose.storage.yml` in repo root:

```yaml
services:
  postgres:
    volumes:
      - ${DATA_ROOT}/postgres:/var/lib/postgresql/data
      - ./infra/init.sql:/docker-entrypoint-initdb.d/init.sql

  redis:
    volumes:
      - ${DATA_ROOT}/redis:/data

  neo4j:
    volumes:
      - ${DATA_ROOT}/neo4j:/data
```

### 5.3 Set `DATA_ROOT`

Add to `.env`:

```bash
DATA_ROOT=/Volumes/ExternalSSD/capstone-data
```

### 5.4 Start with override file

```bash
docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

Notes:

- Keep using both files for all future commands.
- Ensure your external drive is mounted before startup.

---

## 6. Migrating Existing Data to the Larger Drive

If your project already has data in named volumes (`pgdata`, `redisdata`, `neo4jdata`), do this once.

### 6.1 Stop stack

```bash
docker compose down
```

### 6.2 Copy PostgreSQL volume to external drive

```bash
docker run --rm \
  -v capstone_pgdata:/from \
  -v /Volumes/ExternalSSD/capstone-data/postgres:/to \
  alpine sh -c "cd /from && cp -av . /to"
```

### 6.3 Copy Redis volume

```bash
docker run --rm \
  -v capstone_redisdata:/from \
  -v /Volumes/ExternalSSD/capstone-data/redis:/to \
  alpine sh -c "cd /from && cp -av . /to"
```

### 6.4 Copy Neo4j volume (if used)

```bash
docker run --rm \
  -v capstone_neo4jdata:/from \
  -v /Volumes/ExternalSSD/capstone-data/neo4j:/to \
  alpine sh -c "cd /from && cp -av . /to"
```

### 6.5 Start using storage override

```bash
docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

---

## 7. Backup and Restore

## Backup

```bash
mkdir -p backups

docker run --rm \
  -v capstone_pgdata:/source \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /source && tar czf /backup/pgdata_$(date +%F).tar.gz ."
```

Optional Redis backup:

```bash
docker run --rm \
  -v capstone_redisdata:/source \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /source && tar czf /backup/redisdata_$(date +%F).tar.gz ."
```

## Restore

1. Stop stack: `docker compose down`
1. Restore archive into volume:

```bash
docker run --rm \
  -v capstone_pgdata:/target \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /target && rm -rf ./* && tar xzf /backup/pgdata_YYYY-MM-DD.tar.gz -C /target"
```

1. Start stack: `docker compose up -d`

---

## 8. Troubleshooting

### Containers keep restarting

```bash
docker compose ps
docker compose logs --tail=200 agent
docker compose logs --tail=200 postgres
```

### API works but UI cannot connect

Check `frontend` and `agent` both are healthy:

```bash
docker compose ps
docker compose logs --tail=200 frontend
```

### Database auth errors

- Verify `POSTGRES_PASSWORD` in `.env`
- If password changed after initial DB creation, recreate DB volume:

```bash
docker compose down -v
docker compose up -d
```

Warning: `down -v` deletes persistent data.

### External drive setup fails on macOS

- Verify disk is mounted at the same path each boot
- Confirm Docker Desktop has file access permissions for that mount path
- Use Option A if bind mount permissions are inconsistent

---

## 9. Recommended Team Workflow

- Use default `docker compose up -d` for most developers
- Use external-drive setup only for machines with limited internal storage
- Keep one standard `.env` template in team docs (without secrets)
- Run regular PostgreSQL volume backups for shared environments
