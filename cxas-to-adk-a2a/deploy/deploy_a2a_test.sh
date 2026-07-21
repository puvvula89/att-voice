#!/usr/bin/env bash
# Focused deploy of ONLY the CES -> ADK A2A path, for fast iteration once the
# session store (voice engine) + MCP already exist (e.g. after a full deploy_all).
# Skips voice engine / relay / UI. Redeploys the A2A chat engine, then (re)builds
# the CES app + A2A RemoteAgentTool + steering tree + Sales Master callbacks and
# grants the CES P4SA invoke access.
#
# All config from .env. Requires either a prior deploy_all (leaves deploy/.engine_name
# + a deployed MCP) or SESSION_ENGINE_ID + MCP_SERVER_URL set in .env.
set -euo pipefail

# Bundle root is the parent of deploy/ — all relative paths below resolve from there.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
MCP_SERVICE="${MCP_SERVICE:-att-mcp-phone-upgrade-a2a}"
AE_STAGING_BUCKET="${AE_STAGING_BUCKET:-${PROJECT}-agent-engine}"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="python"
export SSL_CERT_FILE="${SSL_CERT_FILE:-$("$PY" -m certifi 2>/dev/null || echo "")}"

# CES P4SA (derive from project number when not set in .env).
if [[ -z "${CES_SERVICE_AGENT:-}" ]]; then
  PNUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  CES_SERVICE_AGENT="service-${PNUM}@gcp-sa-ces.iam.gserviceaccount.com"
fi

# MCP URL: from .env, else describe the deployed MCP service.
if [[ -z "${MCP_SERVER_URL:-}" || "$MCP_SERVER_URL" == http://localhost* ]]; then
  MCP_BASE="$(gcloud run services describe "$MCP_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)' 2>/dev/null || true)"
  [[ -n "$MCP_BASE" ]] || { echo "MCP not found — set MCP_SERVER_URL in .env or run deploy_all first."; exit 1; }
  export MCP_SERVER_URL="${MCP_BASE}/mcp"
fi
echo "▶ MCP_SERVER_URL=$MCP_SERVER_URL"

# Shared session store: from .env, else the voice engine deploy_all created.
SESSION_ENGINE_ID="${SESSION_ENGINE_ID:-}"
if [[ -z "$SESSION_ENGINE_ID" && -f deploy/.engine_name ]]; then
  SESSION_ENGINE_ID="$(cat deploy/.engine_name)"; SESSION_ENGINE_ID="${SESSION_ENGINE_ID##*/}"
fi
[[ -n "$SESSION_ENGINE_ID" ]] || { echo "No SESSION_ENGINE_ID — set it in .env or run deploy_all to create the voice engine."; exit 1; }
echo "▶ SESSION_ENGINE_ID=$SESSION_ENGINE_ID"

# 1. A2A chat engine.
echo "▶ [1/4] A2A chat Agent Engine…"
AE_STAGING_BUCKET="$AE_STAGING_BUCKET" MCP_SERVER_URL="$MCP_SERVER_URL" SESSION_ENGINE_ID="$SESSION_ENGINE_ID" "$PY" deploy/deploy_chat_engine.py
CHAT_AGENT_ENGINE_NAME="$(cat deploy/.chat_engine_name)"
A2A_URL="https://${REGION}-aiplatform.googleapis.com/v1beta1/${CHAT_AGENT_ENGINE_NAME}/a2a"
echo "   A2A_URL=$A2A_URL"

# 2. Grant the CES P4SA invoke access to the Agent Engine A2A endpoint.
echo "▶ [2/4] Grant aiplatform.user to CES P4SA ($CES_SERVICE_AGENT)…"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" --role roles/aiplatform.user --quiet --condition=None >/dev/null
echo "   granted"

# 3. CXAS app + A2A RemoteAgentTool + steering tree.
echo "▶ [3/4] CXAS app + A2A tool + steering tree…"
"$PY" steering/create_cxas_app.py "$A2A_URL"
"$PY" steering/create_steering_tree.py

# 4. Sales Master callbacks (after_model farewell + before/after_tool session threading).
echo "▶ [4/4] Sales Master callbacks…"
"$PY" steering/apply_sales_callbacks.py

echo "✅ A2A test path deployed. CXAS app=${CXAS_APP_ID:-att-ivr-steering-a2a}"
echo "   Test in the Conversational Agents console Simulator."
