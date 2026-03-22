#!/bin/bash
set -euo pipefail

# Dev wrapper: delegate to the unified orchestrator so startup behavior,
# port handling, and live logs are consistent with ./start.sh.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

exec ./start.sh "$@"
