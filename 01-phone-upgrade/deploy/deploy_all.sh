#!/usr/bin/env bash
# One-command deploy of the whole stack to ANY GCP project. All config from .env.
#   MCP (Cloud Run) -> agent (Agent Engine) -> relay (Cloud Run) -> UI (Cloud Run)
# Dynamic outputs (URLs, engine id) are captured and threaded between steps.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

# Load .env into the environment.
if [[ -f .env ]]; then set -a; source .env; set +a; fi

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
MCP_SERVICE="${MCP_SERVICE:-att-mcp-phone-upgrade}"
RELAY_SERVICE="${RELAY_SERVICE:-att-phone-upgrade-relay}"
UI_SERVICE="${UI_SERVICE:-att-phone-upgrade-ui}"
AE_STAGING_BUCKET="${AE_STAGING_BUCKET:-${PROJECT}-agent-engine}"
RELAY_MIN_INSTANCES="${RELAY_MIN_INSTANCES:-1}"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="python"
export SSL_CERT_FILE="${SSL_CERT_FILE:-$("$PY" -m certifi 2>/dev/null || echo "")}"

echo "▶ Deploying to project=$PROJECT region=$REGION"

# 1. MCP data-tool server.
echo "▶ [1/4] MCP server ($MCP_SERVICE)…"
gcloud run deploy "$MCP_SERVICE" --source mcp_server --region "$REGION" --project "$PROJECT" \
  --port 8080 --allow-unauthenticated --quiet
MCP_BASE="$(gcloud run services describe "$MCP_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
export MCP_SERVER_URL="${MCP_BASE}/mcp"
echo "   MCP_SERVER_URL=$MCP_SERVER_URL"

# 2. Voice agent on Agent Engine (consumes MCP_SERVER_URL). Deploy with
#    SESSION_ENGINE_ID unset so it uses its OWN id as the shared session store;
#    the chat engine then points here for cross-channel handoff.
echo "▶ [2/5] Voice Agent Engine (staging gs://$AE_STAGING_BUCKET)…"
gcloud storage buckets create "gs://$AE_STAGING_BUCKET" --location "$REGION" --project "$PROJECT" 2>/dev/null || true
AE_STAGING_BUCKET="$AE_STAGING_BUCKET" MCP_SERVER_URL="$MCP_SERVER_URL" SESSION_ENGINE_ID="" "$PY" deploy/deploy_agent_engine.py
AGENT_ENGINE_NAME="$(cat deploy/.engine_name)"
SESSION_ENGINE_ID="${AGENT_ENGINE_NAME##*/}"   # numeric id = shared session store for BOTH channels
echo "   AGENT_ENGINE_NAME=$AGENT_ENGINE_NAME (session store=$SESSION_ENGINE_ID)"

# 3. Chat agent on a SEPARATE Agent Engine, configured with the voice engine's
#    session store so a conversation started in one channel resumes in the other.
echo "▶ [3/5] Chat Agent Engine…"
AE_STAGING_BUCKET="$AE_STAGING_BUCKET" MCP_SERVER_URL="$MCP_SERVER_URL" SESSION_ENGINE_ID="$SESSION_ENGINE_ID" "$PY" deploy/deploy_chat_engine.py
CHAT_AGENT_ENGINE_NAME="$(cat deploy/.chat_engine_name)"
echo "   CHAT_AGENT_ENGINE_NAME=$CHAT_AGENT_ENGINE_NAME"

# 4. Relay (proxies browser <-> voice (bidi) and <-> chat (async_stream)).
echo "▶ [4/5] Relay ($RELAY_SERVICE)…"
gcloud run deploy "$RELAY_SERVICE" --source . --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 3600 --min-instances "$RELAY_MIN_INSTANCES" --allow-unauthenticated --quiet \
  --set-env-vars "^@^AGENT_ENGINE_NAME=${AGENT_ENGINE_NAME}@CHAT_AGENT_ENGINE_NAME=${CHAT_AGENT_ENGINE_NAME}@GOOGLE_CLOUD_PROJECT=${PROJECT}@GOOGLE_CLOUD_LOCATION=${REGION}@GOOGLE_GENAI_USE_VERTEXAI=TRUE"
RELAY_BASE="$(gcloud run services describe "$RELAY_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
RELAY_WSS="wss://${RELAY_BASE#https://}"
echo "   RELAY=$RELAY_WSS"

# 5. UI (inject the relay URL into config.js, deploy, then restore the committed default).
echo "▶ [5/5] UI ($UI_SERVICE)…"
printf 'window.RELAY_URL = "%s";\n' "$RELAY_WSS" > frontend/config.js
gcloud run deploy "$UI_SERVICE" --source frontend --region "$REGION" --project "$PROJECT" \
  --port 8080 --allow-unauthenticated --quiet
UI_URL="$(gcloud run services describe "$UI_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
git checkout -- frontend/config.js 2>/dev/null || printf 'window.RELAY_URL = "ws://localhost:8000";\n' > frontend/config.js

cat <<EOF

✅ Deployed. Open a UI and click Start:
   Voice UI: $UI_URL
   Chat UI:  $UI_URL/chat.html
   Relay:    $RELAY_WSS
   MCP:      $MCP_SERVER_URL
   Voice:    $AGENT_ENGINE_NAME
   Chat:     $CHAT_AGENT_ENGINE_NAME  (session store=$SESSION_ENGINE_ID)
EOF
