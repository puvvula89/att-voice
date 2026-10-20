# Sourced by the deploy scripts: loads .env and derives the shared names.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f .env ] || { echo "missing .env — copy .env.example and fill it in"; exit 1; }
set -a; . ./.env; set +a

PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SUPPORT_MCP_SERVICE:-cricket-support-mcp}"
PY=.venv/bin/python
step() { echo; echo "== $*"; }
