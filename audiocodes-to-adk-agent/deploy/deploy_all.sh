#!/usr/bin/env bash
# One-command deploy of the AudioCodes steering stack to ANY GCP project.
# All config is read from the gitignored .env — nothing is hardcoded.
#
#   1. ADK multi-agent app  -> Agent Engine     (greeter + specialists, Live/bidi)
#   2. CES billing agent     -> CX Agent Studio  (one-time console build, validated)
#   3. Steering relay        -> Cloud Run        (WebSocket, 15-min demo cap)
#
# Idempotent: the Agent Engine UPDATES in place (stable id) if it exists, else is
# created; Cloud Run updates the service in place. Re-running is safe.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

# Load .env into the environment.
if [[ -f .env ]]; then set -a; source .env; set +a; fi

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
RELAY_SERVICE="${RELAY_SERVICE:-att-steering-relay}"
RELAY_TIMEOUT="${RELAY_TIMEOUT:-900}"            # 15-min demo cap (Cloud Run max 3600)
RELAY_MIN_INSTANCES="${RELAY_MIN_INSTANCES:-1}"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="python"
export SSL_CERT_FILE="${SSL_CERT_FILE:-$("$PY" -m certifi 2>/dev/null || echo "")}"

echo "▶ Deploying AudioCodes steering stack to project=$PROJECT region=$REGION"

# 1. ADK multi-agent app on Agent Engine. MUST run as a module from the module
#    root so relay.* and deploy.* resolve and extra_packages are importable.
#    The staging bucket is derived from project id+number and auto-created.
echo "▶ [1/3] Agent Engine (ADK multi-agent steering app)…"
"$PY" -m deploy.deploy_agent_engine
AE_ENGINE_ID="$(cat deploy/.engine_name)"
echo "   AE_ENGINE_ID=$AE_ENGINE_ID"

# Persist AE_ENGINE_ID back into .env (gitignored) for local harness runs.
if grep -q '^AE_ENGINE_ID=' .env 2>/dev/null; then
  tmp="$(mktemp)"; sed "s|^AE_ENGINE_ID=.*|AE_ENGINE_ID=${AE_ENGINE_ID}|" .env > "$tmp" && mv "$tmp" .env
else
  printf 'AE_ENGINE_ID=%s\n' "$AE_ENGINE_ID" >> .env
fi

# 2. CES billing agent (CX Agent Studio). One-time console build; not scriptable.
echo "▶ [2/3] CES billing agent (CX Agent Studio)…"
if [[ -z "${CES_APP:-}" ]]; then
  echo "   ⚠ CES_APP is empty — build the billing app once in the CX Agent Studio"
  echo "     console, set CES_APP in .env, and re-run. Continuing; the billing route"
  echo "     stays inactive until CES_APP is set."
else
  echo "   CES_APP=$CES_APP (location=${CES_LOCATION:-us})"
fi

# 3. Steering relay on Cloud Run (WebSocket-capable, demo-capped timeout). Reads
#    AE_ENGINE_ID + CES_APP at runtime. ^@^ delimiter keeps values safe.
echo "▶ [3/3] Relay ($RELAY_SERVICE)…"
gcloud run deploy "$RELAY_SERVICE" --source . --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout "$RELAY_TIMEOUT" --min-instances "$RELAY_MIN_INSTANCES" \
  --allow-unauthenticated --quiet \
  --set-env-vars "^@^GOOGLE_GENAI_USE_VERTEXAI=TRUE@GOOGLE_CLOUD_PROJECT=${PROJECT}@GOOGLE_CLOUD_LOCATION=${REGION}@AE_ENGINE_ID=${AE_ENGINE_ID}@CES_APP=${CES_APP:-}@CES_LOCATION=${CES_LOCATION:-us}@LIVE_MODEL=${LIVE_MODEL:-gemini-live-2.5-flash-native-audio}@LIVE_VOICE=${LIVE_VOICE:-Charon}"
RELAY_BASE="$(gcloud run services describe "$RELAY_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
RELAY_WSS="wss://${RELAY_BASE#https://}/ws"
echo "   RELAY=$RELAY_WSS"

cat <<EOF

✅ Deployed.
   Agent Engine: $AE_ENGINE_ID
   Relay WS:     $RELAY_WSS
   CES billing:  ${CES_APP:-<unset — build in CX Agent Studio, set CES_APP, re-run>}

Next: point the mic harness at \$RELAY (or run a local test) and verify the
4 routes (greeter -> internet / phone_upgrade / billing), seamless, no re-greet.
EOF
