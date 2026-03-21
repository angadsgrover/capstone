#!/bin/bash
set -e

BASE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$BASE/.venv/bin/python3" ]; then
  echo "❌ Missing shared .venv Python at $BASE/.venv/bin/python3"
  echo "   Run: bash ./start-local-new-drive.sh"
  exit 1
fi

PYTHON_BIN="$BASE/.venv/bin/python3"

echo "=== Starting MCP servers in SSE mode ==="

# aviation-weather on port 8001
PYTHONPATH="$BASE/aviation-weather-mcp-python" \
  TRANSPORT_MODE=sse PORT=8001 \
  "$PYTHON_BIN" \
  -m aviation_weather_mcp_server &
AVIATION_PID=$!
echo "  aviation-weather → http://localhost:8001/sse  (pid $AVIATION_PID)"

# hk-climate on port 8002
PYTHONPATH="$BASE/hk-climate-mcp-server-python" \
  TRANSPORT_MODE=sse PORT=8002 \
  "$PYTHON_BIN" \
  -m hk_climate_mcp_server &
HK_PID=$!
echo "  hk-climate        → http://localhost:8002/sse  (pid $HK_PID)"

# adsb on port 8003
PYTHONPATH="$BASE/adsb_mcp" \
  TRANSPORT_MODE=sse PORT=8003 \
  "$PYTHON_BIN" \
  "$BASE/adsb_mcp/server.py" &
ADSB_PID=$!
echo "  adsb              → http://localhost:8003/sse  (pid $ADSB_PID)"

echo ""
echo "Waiting 6 s for MCP servers to be ready..."
sleep 6

echo "=== Starting FastAPI agent server on port 8000 ==="
cd "$BASE/agent"
if [ -f "$BASE/.env" ]; then
  set -a
  source "$BASE/.env"
  set +a
fi
if [ -f "$BASE/agent/.env" ]; then
  set -a
  source "$BASE/agent/.env"
  set +a
fi
"$PYTHON_BIN" -m uvicorn server:app --host 0.0.0.0 --port 8000 &
AGENT_PID=$!
echo "  agent API → http://localhost:8000  (pid $AGENT_PID)"

echo ""
echo "Waiting 10 s for agent to initialise..."
sleep 10

echo "=== Starting Vite frontend on port 5173 ==="
cd "$BASE/frontend-app"
trap 'echo "Stopping all services..."; kill $AVIATION_PID $HK_PID $ADSB_PID $AGENT_PID 2>/dev/null || true' EXIT
npm run dev
