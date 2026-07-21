#!/usr/bin/env bash
# One-command deploy of the WHOLE self-contained bundle to any GCP project.
# All config from .env. Ordered, with dynamic outputs threaded between steps:
#   MCP -> voice engine -> chat engine (native A2A) -> relay -> UI
#     -> CXAS app + A2A RemoteAgentTool -> steering tree -> Sales Master callbacks
set -euo pipefail

# Bundle root is the parent of deploy/ — all relative paths below resolve from there.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
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

# CES P4SA (per-project service agent). CES uses it by default to authenticate to
# the Agent Engine A2A endpoint. Derive from the project number when not set in .env.
if [[ -z "${CES_SERVICE_AGENT:-}" ]]; then
  PNUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  CES_SERVICE_AGENT="service-${PNUM}@gcp-sa-ces.iam.gserviceaccount.com"
fi

echo "▶ Deploying bundle to project=$PROJECT region=$REGION"

# 1. MCP data-tool server. Kept warm (min-instances=1) so the first turn's get_lines
#    doesn't pay a cold start (~4s otherwise). Override via MCP_MIN_INSTANCES.
echo "▶ [1/8] MCP server ($MCP_SERVICE, min-instances=${MCP_MIN_INSTANCES:-1})…"
gcloud run deploy "$MCP_SERVICE" --source mcp_server --region "$REGION" --project "$PROJECT" \
  --port 8080 --min-instances "${MCP_MIN_INSTANCES:-1}" --allow-unauthenticated --quiet
MCP_BASE="$(gcloud run services describe "$MCP_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
export MCP_SERVER_URL="${MCP_BASE}/mcp"
echo "   MCP_SERVER_URL=$MCP_SERVER_URL"

# 2. Voice agent (Agent Engine). Idempotent: updates in place, id stable across deploys.
PINNED_SESSION_ENGINE_ID="${SESSION_ENGINE_ID:-}"
echo "▶ [2/8] Voice Agent Engine (staging gs://$AE_STAGING_BUCKET)…"
gcloud storage buckets create "gs://$AE_STAGING_BUCKET" --location "$REGION" --project "$PROJECT" 2>/dev/null || true
AE_STAGING_BUCKET="$AE_STAGING_BUCKET" MCP_SERVER_URL="$MCP_SERVER_URL" SESSION_ENGINE_ID="$PINNED_SESSION_ENGINE_ID" "$PY" deploy/deploy_agent_engine.py
AGENT_ENGINE_NAME="$(cat deploy/.engine_name)"
SESSION_ENGINE_ID="${PINNED_SESSION_ENGINE_ID:-${AGENT_ENGINE_NAME##*/}}"
echo "   AGENT_ENGINE_NAME=$AGENT_ENGINE_NAME (session store=$SESSION_ENGINE_ID)"

# 3. Chat agent (separate Agent Engine, sharing the voice engine's session store).
echo "▶ [3/8] Chat Agent Engine…"
AE_STAGING_BUCKET="$AE_STAGING_BUCKET" MCP_SERVER_URL="$MCP_SERVER_URL" SESSION_ENGINE_ID="$SESSION_ENGINE_ID" "$PY" deploy/deploy_chat_engine.py
CHAT_AGENT_ENGINE_NAME="$(cat deploy/.chat_engine_name)"
echo "   CHAT_AGENT_ENGINE_NAME=$CHAT_AGENT_ENGINE_NAME"

# 4. Relay (browser <-> voice bidi and <-> chat async_stream). Built from root Dockerfile.
echo "▶ [4/8] Relay ($RELAY_SERVICE)…"
gcloud run deploy "$RELAY_SERVICE" --source . --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 3600 --min-instances "$RELAY_MIN_INSTANCES" --allow-unauthenticated --quiet \
  --set-env-vars "^@^AGENT_ENGINE_NAME=${AGENT_ENGINE_NAME}@CHAT_AGENT_ENGINE_NAME=${CHAT_AGENT_ENGINE_NAME}@GOOGLE_CLOUD_PROJECT=${PROJECT}@GOOGLE_CLOUD_LOCATION=${REGION}@GOOGLE_GENAI_USE_VERTEXAI=TRUE"
RELAY_BASE="$(gcloud run services describe "$RELAY_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
RELAY_WSS="wss://${RELAY_BASE#https://}"
echo "   RELAY=$RELAY_WSS"

# 5. UI (inject the relay URL into config.js, deploy, then restore the default).
echo "▶ [5/8] UI ($UI_SERVICE)…"
printf 'window.RELAY_URL = "%s";\n' "$RELAY_WSS" > frontend/config.js
gcloud run deploy "$UI_SERVICE" --source frontend --region "$REGION" --project "$PROJECT" \
  --port 8080 --allow-unauthenticated --quiet
UI_URL="$(gcloud run services describe "$UI_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
git checkout -- frontend/config.js 2>/dev/null || printf 'window.RELAY_URL = "ws://localhost:8000";\n' > frontend/config.js

# 6. Derive the chat engine's NATIVE A2A endpoint. No adapter service — CES calls
#    the Agent Engine A2A URL directly (RemoteAgentTool, P4SA auth).
A2A_URL="https://${REGION}-aiplatform.googleapis.com/v1beta1/${CHAT_AGENT_ENGINE_NAME}/a2a"
echo "▶ [6/8] Chat engine A2A endpoint: $A2A_URL"

# 7. Let the CES P4SA invoke the Agent Engine A2A endpoint (Vertex AI User grants
#    reasoningEngine query/stream). This is what P4SA-by-default auth needs.
echo "▶ [7/8] Grant aiplatform.user to CES P4SA ($CES_SERVICE_AGENT)…"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" --role roles/aiplatform.user --quiet --condition=None >/dev/null
echo "   granted"

# 8. CXAS app + A2A RemoteAgentTool (pointed at the Agent Engine A2A URL) then the
#    steering tree (agents + customer_id var) and Sales Master callbacks
#    (after_model farewell + before_tool/after_tool session-id threading).
echo "▶ [8/8] CXAS app + A2A tool + steering tree + callbacks…"
"$PY" steering/create_cxas_app.py "$A2A_URL"
"$PY" steering/create_steering_tree.py
"$PY" steering/apply_sales_callbacks.py

cat <<EOF

✅ Bundle deployed.
   Voice UI:  $UI_URL
   Chat UI:   $UI_URL/chat.html
   Relay:     $RELAY_WSS
   MCP:       $MCP_SERVER_URL
   Voice:     $AGENT_ENGINE_NAME  (session store=$SESSION_ENGINE_ID)
   Chat:      $CHAT_AGENT_ENGINE_NAME  (native A2A endpoint)
   A2A URL:   $A2A_URL
   CXAS app:  ${CXAS_APP_ID:-att-ivr-steering-a2a}  (Global Concierge -> Consumer -> Sales Master + Care)

Test the CXAS path in the Conversational Agents console (Simulator), or the browser
voice/chat via the UI URLs above.
EOF
