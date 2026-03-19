#!/bin/bash
# Unified entry point for Aviation Intelligence Platform
#
# This is a simple wrapper around start.py for convenience.
# All advanced options should use start.py directly.
#
# Usage:
#   ./start.sh              # Start all services locally
#   ./start.sh --docker     # Start with Docker Compose
#   ./start.sh --test       # Start + run integration tests
#   ./start.sh --check      # Health checks only

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10 or higher."
    exit 1
fi

# Map simplified args to start.py args
ARGS=()

for arg in "$@"; do
    case $arg in
        --docker)
            ARGS+=("--docker")
            ;;
        --test)
            ARGS+=("--test")
            ;;
        --check)
            ARGS+=("--check-only")
            ;;
        --no-frontend)
            ARGS+=("--skip-frontend")
            ;;
        --detach|-d)
            ARGS+=("--detach")
            ;;
        --help|-h)
            cat << EOF
Aviation Intelligence Platform - Unified Startup

Usage:
  ./start.sh [OPTIONS]

Options:
  --docker          Use Docker Compose (recommended for production)
  --test            Run integration tests after startup
  --check           Health checks only (no startup)
  --no-frontend     Skip frontend dev server
  --detach, -d      Start in background and exit
  --help, -h        Show this help message

Examples:
  ./start.sh                    # Start all services locally
  ./start.sh --docker           # Start with Docker (production)
  ./start.sh --test             # Start + run tests
  ./start.sh --check            # Just health checks
  ./start.sh --no-frontend      # API only (no UI)

For advanced options, use start.py directly:
  python3 start.py --help

Documentation:
  - Quick Start:  QUICKSTART.md
  - Development:  DEVELOPMENT.md
  - README:       README.md
EOF
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $arg"
            echo "Run ./start.sh --help for usage"
            exit 1
            ;;
    esac
done

# Run start.py with collected arguments
cd "$SCRIPT_DIR"
exec python3 start.py "${ARGS[@]}"
