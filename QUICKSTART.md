# Quick Start Reference

## Docker (Recommended for First Time)

```bash
cp .env.example .env
# Edit .env: fill LLM_API_KEY, POSTGRES_PASSWORD, BASE_URL, MODEL_CHOICE

docker compose up -d
# Wait ~30s, then:
# Frontend: http://localhost:80
# API: http://localhost:8000/docs
# Adminer (dev): docker compose --profile dev up -d → http://localhost:8080
```

Stop:
```bash
docker compose down
```

With AGE Graph (optional):
```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.graph.yml up -d
```

---

## Local Development

```bash
# 1. Activate agent venv
cd agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Start MCP servers (3 terminals)
# Terminal A:
cd aviation-weather-mcp-python && TRANSPORT_MODE=sse PORT=8001 python -m aviation_weather_mcp_server

# Terminal B:
cd hk-climate-mcp-server-python && TRANSPORT_MODE=sse PORT=8002 python -m hk_climate_mcp_server

# Terminal C:
cd adsb_mcp && TRANSPORT_MODE=sse PORT=8003 python server.py --sse --host 0.0.0.0 --port 8003

# 3. Start agent (Terminal D)
cd agent && python server.py
# → http://localhost:8000

# 4. Start frontend (Terminal E)
cd frontend-app && npm install && npm run dev
# → http://localhost:5173
```

---

## Test API Endpoints

### Query Agent
```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello", "session_id": "test-1"}'
```

### Stream Tokens
```bash
curl "http://localhost:8000/api/agent/stream?input=Weather%20at%20VHHH&session_id=test-2"
```

### Workflow Events
```bash
# Terminal 1: Trigger
curl -X POST http://localhost:8000/api/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"input": "Track CX680", "session_id": "test-3"}'

# Terminal 2: Watch events
curl "http://localhost:8000/api/agent/events?session_id=test-3"
```

---

## Database

```bash
# Local postgres
psql -U capstone

# View conversations
SELECT * FROM conversations LIMIT 5;

# View embeddings
SELECT COUNT(*) FROM embeddings;

# Check METAR history
SELECT COUNT(*) FROM metar_history;
```

---

## Env Variables

| Variable | Required | Example |
|----------|----------|---------|
| LLM_API_KEY | ✅ | sk-... |
| BASE_URL | ✅ | https://openrouter.ai/api/v1 |
| MODEL_CHOICE | ✅ | qwen/qwen3-8b |
| POSTGRES_PASSWORD | ✅ | secure_pass |
| EMBED_API_KEY | ❌ | (defaults to LLM_API_KEY) |
| EMBED_BASE_URL | ❌ | (defaults to BASE_URL) |
| LANGFUSE_PUBLIC_KEY | ❌ | pk-... |
| LANGFUSE_SECRET_KEY | ❌ | sk-... |

---

## Useful Commands

```bash
# Docker logs
docker compose logs -f agent        # watch agent
docker compose logs mcp-aviation-wx # watch MCP server

# Rebuild
docker compose build --no-cache

# Clean up
docker compose down -v  # remove volumes too

# Enter postgres
docker compose exec postgres psql -U capstone

# Run tests
cd agent && python -m pytest tools/ -v
```

---

## Frontend URLs

| Tab | URL |
|-----|-----|
| Chat | / |
| Workflow | /workflow |
| Logs | /logs |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Services won't start | Check logs: `docker compose logs` |
| MCP connection error | Ensure all 3 MCP servers running on 8001/8002/8003 |
| DB error | Verify POSTGRES_PASSWORD matches compose env |
| Empty responses | Check LLM_API_KEY is valid |
| No embeddings | Verify EMBED_API_KEY if using separate provider |

---

For detailed guides, see:
- **Setup**: [README.md](./README.md)
- **Development**: [DEVELOPMENT.md](./DEVELOPMENT.md)
