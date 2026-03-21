#!/usr/bin/env bash
set -euo pipefail

# One-command local bootstrap for running without Docker from a new drive.
# It installs frontend + Python dependencies into ONE shared virtualenv,
# then starts services via start.sh.

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR"

WITH_INFRA=false
WITH_GRAPH=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --with-infra)
      WITH_INFRA=true
      ;;
    --with-graph)
      WITH_INFRA=true
      WITH_GRAPH=true
      ;;
    *)
      PASSTHROUGH_ARGS+=("$arg")
      ;;
  esac
done

pick_compose() {
  if command -v docker >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi
  if command -v podman >/dev/null 2>&1; then
    echo "podman compose"
    return
  fi
  echo ""
}

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm not found. Install Node.js first."
  exit 1
fi

COMPOSE_CMD="$(pick_compose)"
if $WITH_INFRA && [ -z "$COMPOSE_CMD" ]; then
  echo "Error: neither docker nor podman was found. Install one, or run without --with-infra."
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

load_dotenv_safe() {
  local env_file="$1"
  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    # Trim leading/trailing whitespace
    local line
    line="${raw_line#${raw_line%%[![:space:]]*}}"
    line="${line%${line##*[![:space:]]}}"

    # Skip empty/comment-only lines
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac

    # Accept KEY=VALUE lines only
    if ! printf '%s' "$line" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*='; then
      continue
    fi

    local key="${line%%=*}"
    local value="${line#*=}"

    # Strip common inline comments starting with space-hash.
    # Example: FOO=bar # comment
    value="${value%%\ #*}"

    # Trim whitespace around value after comment strip
    value="${value#${value%%[![:space:]]*}}"
    value="${value%${value##*[![:space:]]}}"

    export "$key=$value"
  done < "$env_file"
}

# Export variables from .env so infra checks and compose interpolation can use them.
load_dotenv_safe ".env"

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

setup_shared_python_env() {
  echo "[1/2] Setting up shared Python environment..."
  ensure_venv ".venv"
  source .venv/bin/activate
  pip install --upgrade pip

  # Install local MCP packages first so name-based requirements resolve locally.
  pip install -e aviation-weather-mcp-python
  pip install -e hk-climate-mcp-server-python
  pip install -e adsb_mcp

  # Install agent requirements last (includes shared deps and local package names).
  pip install -r agent/requirements.txt
  deactivate
}

setup_frontend() {
  echo "[2/2] Installing frontend dependencies..."
  (cd frontend-app && npm ci)
}

start_infra_if_requested() {
  if ! $WITH_INFRA; then
    return
  fi

  echo "Starting local infrastructure with compose (Postgres + Redis${WITH_GRAPH:+ + Neo4j})..."
  echo "Compose engine: $COMPOSE_CMD"

  if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "Error: POSTGRES_PASSWORD is not set in environment/.env (required for compose postgres)."
    exit 1
  fi

  if $WITH_GRAPH && [ -z "${NEO4J_PASSWORD:-}" ]; then
    echo "Error: NEO4J_PASSWORD is not set in environment/.env (required for --with-graph)."
    exit 1
  fi

  local COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.local-infra.yml)

  if $WITH_GRAPH; then
    $COMPOSE_CMD "${COMPOSE_FILES[@]}" --profile graph up -d postgres redis neo4j
  else
    $COMPOSE_CMD "${COMPOSE_FILES[@]}" up -d postgres redis
  fi

  # Run DB initialization explicitly (instead of bind-mounting init.sql)
  # to avoid mount failures on Podman with external-drive paths.
  if [ -f "infra/init.sql" ]; then
    echo "Initializing PostgreSQL schema from infra/init.sql..."
    $COMPOSE_CMD "${COMPOSE_FILES[@]}" exec -T postgres psql -U capstone -d capstone < infra/init.sql || true
  fi
}

setup_shared_python_env
setup_frontend
start_infra_if_requested

echo "Bootstrap complete. Starting local stack..."
exec ./start.sh "${PASSTHROUGH_ARGS[@]}"
