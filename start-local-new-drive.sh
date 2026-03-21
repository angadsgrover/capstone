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
    return
  fi

  if command -v python3.13 >/dev/null 2>&1; then
    echo "python3.13"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    local ver
    ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$ver" in
      3.12|3.13)
        echo "python3"
        return
        ;;
    esac
  fi

  echo ""
}

PYTHON_BIN="$(pick_python)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python 3.12 or 3.13 is required for local non-Docker setup."
  echo "Current python3 is unsupported (for example 3.14 can fail on pinned dependencies)."
  exit 1
fi

echo "Using Python interpreter: $PYTHON_BIN"

ensure_venv() {
  local venv_path="$1"
  local want_ver
  want_ver="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

  if [ -x "$venv_path/bin/python" ]; then
    local have_ver
    have_ver="$($venv_path/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [ "$have_ver" != "$want_ver" ]; then
      echo "Recreating $venv_path (python $have_ver -> $want_ver)"
      rm -rf "$venv_path"
    elif ! "$venv_path/bin/python" -c 'import pip, setuptools' >/dev/null 2>&1; then
      echo "Recreating $venv_path (detected broken pip/setuptools metadata)"
      rm -rf "$venv_path"
    fi
  fi

  if [ ! -d "$venv_path" ]; then
    "$PYTHON_BIN" -m venv "$venv_path"
  fi
}

setup_agent() {
  echo "[4/5] Setting up agent environment..."
  ensure_venv "agent/.venv"
  source agent/.venv/bin/activate
  pip install --upgrade pip

  # agent/requirements.txt references local MCP packages by name.
  # Install them into the same environment first so resolution does not hit PyPI.
  pip install -e aviation-weather-mcp-python
  pip install -e hk-climate-mcp-server-python

  pip install -r agent/requirements.txt
  deactivate
}

setup_mcp_project() {
  local path="$1"
  local label="$2"
  local step="$3"

  echo "[$step/5] Setting up ${label}..."
  ensure_venv "$path/.venv"
  source "$path/.venv/bin/activate"
  pip install --upgrade pip
  pip install -e "$path"
  deactivate
}

setup_frontend() {
  echo "[5/5] Installing frontend dependencies..."
  (cd frontend-app && npm ci)
}

setup_mcp_project "aviation-weather-mcp-python" "aviation weather MCP" "1"
setup_mcp_project "hk-climate-mcp-server-python" "HK climate MCP" "2"
setup_mcp_project "adsb_mcp" "ADS-B MCP" "3"
setup_agent
setup_frontend

echo "Bootstrap complete. Starting local stack..."
exec ./start.sh "$@"
