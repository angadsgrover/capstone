# Aviation AI - Unified Command Interface
# Run 'make help' to see all available commands

.PHONY: help setup dev docker docker-prod docker-stop logs test health clean

# Default target
help:
	@echo "╔══════════════════════════════════════════════════════════════════╗"
	@echo "║               Aviation AI - Command Reference                    ║"
	@echo "╠══════════════════════════════════════════════════════════════════╣"
	@echo "║ SETUP                                                            ║"
	@echo "║   make setup          Install all dependencies (first time)      ║"
	@echo "║   make env            Copy .env.example to .env                  ║"
	@echo "║                                                                  ║"
	@echo "║ DEVELOPMENT (Local Python processes)                             ║"
	@echo "║   make dev            Start all services locally                 ║"
	@echo "║   make dev-agent      Start agent only (MCP servers separate)    ║"
	@echo "║   make dev-mcp        Start MCP servers only                     ║"
	@echo "║                                                                  ║"
	@echo "║ DOCKER                                                           ║"
	@echo "║   make docker         Start with Docker (development)            ║"
	@echo "║   make docker-prod    Start with Docker (production settings)    ║"
	@echo "║   make docker-graph   Start with Neo4j graph database            ║"
	@echo "║   make docker-stop    Stop all Docker containers                 ║"
	@echo "║   make docker-clean   Stop and remove volumes                    ║"
	@echo "║                                                                  ║"
	@echo "║ OPERATIONS                                                       ║"
	@echo "║   make logs           Tail all container logs                    ║"
	@echo "║   make logs-agent     Tail agent logs only                       ║"
	@echo "║   make health         Check health of all services               ║"
	@echo "║   make test           Run integration tests                      ║"
	@echo "║   make ingest         Trigger METAR/TAF ingestion                ║"
	@echo "║   make eval-langsmith Run LangSmith workflow evaluation          ║"
	@echo "║   make eval-langsmith-local Run evaluation without upload        ║"
	@echo "║                                                                  ║"
	@echo "║ DATABASE                                                         ║"
	@echo "║   make db-shell       Open PostgreSQL shell                      ║"
	@echo "║   make db-embeddings  Show embedding counts                      ║"
	@echo "║   make redis-cli      Open Redis CLI                             ║"
	@echo "╚══════════════════════════════════════════════════════════════════╝"

# ── Setup ──────────────────────────────────────────────────────────────────────

setup:
	@echo "Setting up Aviation AI..."
	@if [ ! -f .env ]; then cp agent/.env.example .env && echo "Created .env from template"; fi
	@cd agent && python -m venv .venv && .venv/bin/pip install -r requirements.txt
	@cd frontend-app && npm install
	@echo "Setup complete! Edit .env with your API keys, then run 'make dev' or 'make docker'"

env:
	@if [ ! -f .env ]; then cp agent/.env.example .env && echo "Created .env"; else echo ".env already exists"; fi

# ── Development (Local) ────────────────────────────────────────────────────────

dev:
	@echo "Starting Aviation AI (local development)..."
	@./start.sh

dev-agent:
	@echo "Starting Agent only..."
	@cd agent && .venv/bin/python -m uvicorn server:app --reload --port 8000

dev-mcp:
	@echo "Starting MCP servers..."
	@cd aviation-weather-mcp-python && TRANSPORT_MODE=sse PORT=8001 ../.venv/bin/python main.py &
	@cd hk-climate-mcp-server-python && TRANSPORT_MODE=sse PORT=8002 ../.venv/bin/python main.py &
	@cd adsb_mcp && TRANSPORT_MODE=sse PORT=8003 ../.venv/bin/python main.py &
	@echo "MCP servers started on ports 8001, 8002, 8003"

# ── Docker ─────────────────────────────────────────────────────────────────────

docker:
	@echo "Starting Aviation AI (Docker)..."
	@docker compose up -d --build
	@echo "Services starting... Run 'make health' to check status"
	@echo "Frontend: http://localhost:80"

docker-prod:
	@echo "Starting Aviation AI (Docker Production)..."
	@docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
	@echo "Production services started. Run 'make health' to verify."

docker-graph:
	@echo "Starting Aviation AI with Neo4j..."
	@docker compose --profile graph up -d --build
	@echo "Neo4j available at http://localhost:7474"

docker-stop:
	@docker compose down

docker-clean:
	@docker compose down -v
	@echo "Containers and volumes removed"

# ── Logs ───────────────────────────────────────────────────────────────────────

logs:
	@docker compose logs -f

logs-agent:
	@docker compose logs -f agent

logs-mcp:
	@docker compose logs -f mcp-aviation-wx mcp-hk-climate mcp-adsb

# ── Health & Testing ───────────────────────────────────────────────────────────

health:
	@echo "╔══════════════════════════════════════════════════════════════════╗"
	@echo "║                    Service Health Check                          ║"
	@echo "╠══════════════════════════════════════════════════════════════════╣"
	@printf "║ %-20s " "PostgreSQL:" && (docker exec $$(docker compose ps -q postgres 2>/dev/null) pg_isready -U capstone >/dev/null 2>&1 && echo "✅ Ready" || echo "❌ Down")
	@printf "║ %-20s " "Redis:" && (docker exec $$(docker compose ps -q redis 2>/dev/null) redis-cli ping 2>/dev/null | grep -q PONG && echo "✅ Ready" || echo "❌ Down")
	@printf "║ %-20s " "Agent API:" && (curl -sf http://localhost:8000/health >/dev/null 2>&1 && echo "✅ Ready" || echo "❌ Down")
	@printf "║ %-20s " "MCP Aviation:" && (curl -sf http://localhost:8001/sse >/dev/null 2>&1 && echo "✅ Ready" || echo "⚠️  Internal only")
	@printf "║ %-20s " "MCP HK Climate:" && (curl -sf http://localhost:8002/sse >/dev/null 2>&1 && echo "✅ Ready" || echo "⚠️  Internal only")
	@printf "║ %-20s " "MCP ADS-B:" && (curl -sf http://localhost:8003/sse >/dev/null 2>&1 && echo "✅ Ready" || echo "⚠️  Internal only")
	@printf "║ %-20s " "Frontend:" && (curl -sf http://localhost:80 >/dev/null 2>&1 && echo "✅ Ready" || echo "❌ Down")
	@echo "╚══════════════════════════════════════════════════════════════════╝"

test:
	@echo "Running integration tests..."
	@curl -sf http://localhost:8000/health && echo "✅ Agent healthy" || (echo "❌ Agent not responding" && exit 1)
	@echo "Testing chat endpoint..."
	@curl -sf -X POST http://localhost:8000/api/agent \
		-H "Content-Type: application/json" \
		-d '{"input":"What is the METAR for VHHH?","session_id":"test"}' | head -c 200
	@echo "\n✅ Tests passed"

# ── Database Operations ────────────────────────────────────────────────────────

db-shell:
	@docker exec -it $$(docker compose ps -q postgres) psql -U capstone

db-embeddings:
	@echo "Embedding counts by source type:"
	@docker exec $$(docker compose ps -q postgres) psql -U capstone -c \
		"SELECT source_type, COUNT(*) as count FROM embeddings GROUP BY source_type ORDER BY count DESC;"

db-conversations:
	@docker exec $$(docker compose ps -q postgres) psql -U capstone -c \
		"SELECT session_id, COUNT(*) as messages FROM conversations GROUP BY session_id ORDER BY MAX(created_at) DESC LIMIT 10;"

redis-cli:
	@docker exec -it $$(docker compose ps -q redis) redis-cli

# ── Ingestion ──────────────────────────────────────────────────────────────────

ingest:
	@echo "Triggering METAR/TAF ingestion..."
	@docker exec $$(docker compose ps -q agent) python -c "from ingestion.scheduler import run_once; import asyncio; asyncio.run(run_once())"

ingest-local:
	@cd agent && .venv/bin/python -c "from ingestion.scheduler import run_once; import asyncio; asyncio.run(run_once())"

# ── Evaluation ───────────────────────────────────────────────────────────────

eval-langsmith:
	@echo "Running LangSmith evaluation (uploaded experiment)..."
	@cd agent && .venv/bin/python -m evaluation.runner

eval-langsmith-local:
	@echo "Running LangSmith evaluation in local mode (no upload)..."
	@cd agent && .venv/bin/python -m evaluation.runner --local

# ── Cleanup ────────────────────────────────────────────────────────────────────

clean:
	@echo "Cleaning up..."
	@docker compose down -v --remove-orphans
	@rm -rf agent/__pycache__ agent/**/__pycache__
	@rm -rf frontend-app/dist frontend-app/node_modules/.cache
	@echo "Cleanup complete"
