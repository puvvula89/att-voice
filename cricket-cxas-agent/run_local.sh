#!/usr/bin/env bash
# Run the support MCP server locally on :8080 with .env loaded.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
exec .venv/bin/uvicorn support_mcp.server:app --host 0.0.0.0 --port "${PORT:-8080}"
