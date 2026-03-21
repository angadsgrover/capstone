#!/usr/bin/env bash
set -euo pipefail

# One-command local bootstrap for running without Docker from a new drive.
# It installs frontend + Python dependencies, then starts services via start.sh.

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR"

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm not found. Install Node.js first."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 not found. Install Python first."
  exit 1
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
    echo "Please edit .env with real keys/passwords before production use."
  else
    echo "Error: .env and .env.example are both missing."
    exit 1
  fi
fi

pick_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12"
  else
    echo "python3"
  fi
}

PYTHON_BIN="$(pick_python)"
echo "Using Python interpreter: $PYTHON_BIN"

setup_agent() {
  echo "[1/5] Setting up agent environment..."
  if [ ! -d "agent/.venv" ]; then
    "$PYTHON_BIN" -m venv agent/.venv
  fi
  source agent/.venv/bin/activate
  pip install --upgrade pip
  pip install -r agent/requirements.txt
  deactivate
}

setup_mcp_project() {
  local path="$1"
  local label="$2"

  echo "[mcp] Setting up ${label}..."
  if [ ! -d "$path/.venv" ]; then
    "$PYTHON_BIN" -m venv "$path/.venv"
  fi
  source "$path/.venv/bin/activate"
  pip install --upgrade pip
  pip install -e "$path"
  deactivate
}

setup_frontend() {
  echo "[5/5] Installing frontend dependencies..."
  (cd frontend-app && npm ci)
}

setup_agent
setup_mcp_project "aviation-weather-mcp-python" "aviation weather MCP"
setup_mcp_project "hk-climate-mcp-server-python" "HK climate MCP"
setup_mcp_project "adsb_mcp" "ADS-B MCP"
setup_frontend

echo "Bootstrap complete. Starting local stack..."
exec ./start.sh "$@"
