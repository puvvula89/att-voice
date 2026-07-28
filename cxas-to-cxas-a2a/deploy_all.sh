#!/usr/bin/env bash
# One command, whole stack. Deploys every component of this bundle in dependency
# order and prints the live URLs at the end.
#
#   bash deploy_all.sh
#
# Expect ~10-15 minutes, nearly all of it Cloud Build compiling three container
# images.
#
#   1  chat app     CX Agent Studio                      — created only if missing
#   2  voice app    CX Agent Studio                      — created only if missing
#   3  hydration    Cloud Run (private) + run.invoker + OpenAPI toolset
#   4  attach       hydration toolset + firing callback on the root agent
#   5  relay        Cloud Run (PUBLIC) + roles/ces.client on its service account
#   6  UI           Cloud Run (PUBLIC), pointed at the relay
#
# ⚠️ RUN THIS YOURSELF, INTERACTIVELY. Steps 3 and 5 bind IAM policies; an
#    unattended shell may be refused them.
#
# ⚠️ THE RELAY AND UI ARE PUBLIC. A browser cannot attach an OIDC token to a
#    WebSocket handshake, so a private relay is unreachable from a web page.
#    Anyone with the URL can drive the app and spend its quota. Tear the public
#    surface down with destroy_all.sh when you are done.
#
# IDEMPOTENT. Cloud Run deploys create a new revision in place (URLs are stable),
# the toolset is recreated, and the callback/instruction are rewritten. The two
# CX Agent Studio apps are the exception: creating an app registers its agents and
# assigns their IDs, so re-creating one would overwrite agents you may have edited
# since. This script skips an app that already exists.
#
# To redeploy a SINGLE component, see "Deploy one component at a time" in the
# README — it lists the raw gcloud commands each step below runs.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "ERROR: no .env here. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi
set -a; source .env; set +a

PROJECT="${CXAS_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
CXAS_LOC="${CXAS_LOCATION:-us}"
VOICE_APP="${VOICE_APP_ID:-cxas-voice-and-chat}"
CHAT_APP="${CHAT_APP_ID:-cxas-chat}"
HYDRATION_SERVICE="${HYDRATION_SERVICE:-cxas-hydration}"
RELAY_SERVICE="${RELAY_SERVICE:-cxas-web-relay}"
UI_SERVICE="${UI_SERVICE:-cxas-web-ui}"

if [[ -z "$PROJECT" ]]; then
  echo "ERROR: set CXAS_PROJECT (or GOOGLE_CLOUD_PROJECT) in .env" >&2
  exit 1
fi

# --- interpreter -------------------------------------------------------------
# Prefer an explicit $PY, then a local .venv, then build one. Self-contained on
# purpose: this bundle should not need a sibling bundle's virtualenv to deploy.
if [[ -z "${PY:-}" ]]; then
  if [[ -x .venv/bin/python ]]; then
    PY=".venv/bin/python"
  else
    echo "▶ [0/6] No .venv — creating one and installing requirements"
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
    PY=".venv/bin/python"
    echo "   ready"
  fi
fi
PY="$(cd "$(dirname "$PY")" && pwd)/$(basename "$PY")"   # absolutise for subshells

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"

echo "project=$PROJECT ($PROJECT_NUMBER)  region=$REGION  cxas_location=$CXAS_LOC"
echo "voice_app=$VOICE_APP  chat_app=$CHAT_APP"
echo

# Does a CX Agent Studio app already exist? Creating twice is what we avoid.
app_exists() {
  "$PY" - "$1" <<'PYEOF' 2>/dev/null
import os, sys
from dotenv import load_dotenv
load_dotenv(".env")
from cxas_scrapi.core.variables import Variables
project = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
location = os.environ.get("CXAS_LOCATION", "us")
name = f"projects/{project}/locations/{location}/apps/{sys.argv[1]}"
try:
    Variables(app_name=name).get_app(name)
except Exception:
    sys.exit(1)
PYEOF
}

# --- 1. chat app -------------------------------------------------------------
echo "▶ [1/6] CX Agent Studio app: $CHAT_APP"
if app_exists "$CHAT_APP"; then
  echo "   exists — skipping creation (edit it in the console, not here)"
else
  "$PY" bootstrap/create_chat_app.py
fi

# --- 2. voice app ------------------------------------------------------------
echo
echo "▶ [2/6] CX Agent Studio app: $VOICE_APP"
if app_exists "$VOICE_APP"; then
  echo "   exists — skipping creation (edit it in the console, not here)"
else
  # CHAT_A2A_URL is optional; without it the A2A wrapper carries only end_session.
  "$PY" bootstrap/create_voice_app.py "${CHAT_A2A_URL:-}"
fi

# --- 3. hydration service (private) + run.invoker + toolset -------------------
# LATENCY: this runs on the caller's FIRST turn, so a cold start would be heard as
# dead air. min-instances=1 keeps an instance resident, cpu-boost speeds the start
# it does pay, and cpu-throttling=off keeps the idle instance responsive instead
# of being throttled to near-zero between requests.
echo
echo "▶ [3/6] Hydration service → Cloud Run (private, warm, boosted)"
gcloud run deploy "$HYDRATION_SERVICE" \
  --source hydration \
  --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 60 \
  --min-instances 1 --max-instances "${HYDRATION_MAX_INSTANCES:-3}" \
  --cpu 2 --memory 1Gi \
  --cpu-boost \
  --no-cpu-throttling \
  --no-allow-unauthenticated \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOC}@VOICE_APP_ID=${VOICE_APP}" \
  --quiet

HYDRATION_URL="$(gcloud run services describe "$HYDRATION_SERVICE" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
echo "   url: $HYDRATION_URL"

# The service reads prior conversations with get_conversation, which needs
# ces.conversations.get — that lives in roles/ces.viewer, NOT in roles/ces.client
# (which is sessions and tool execution only). Both are needed, on the same
# default compute SA, for different reasons.
#
# Miss this one and the failure is SILENT: the service catches the error and
# degrades to found=false, which is indistinguishable from "this customer has no
# history". The agent greets normally and nothing looks broken.
HYDRATION_SA="${HYDRATION_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
echo "   granting roles/ces.viewer to $HYDRATION_SA"
if gcloud projects add-iam-policy-binding "$PROJECT" \
     --member "serviceAccount:${HYDRATION_SA}" \
     --role roles/ces.viewer --condition=None --quiet >/dev/null 2>&1; then
  echo "   granted"
else
  echo "   ⚠ COULD NOT BIND roles/ces.viewer to ${HYDRATION_SA}."
  echo "     Without it hydration always returns found=false — silently."
  echo "       gcloud projects add-iam-policy-binding $PROJECT \\"
  echo "         --member serviceAccount:${HYDRATION_SA} --role roles/ces.viewer"
fi

# The CES service agent mints the OIDC token CXAS uses to call the private service.
CES_SERVICE_AGENT="${CES_SERVICE_AGENT:-service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com}"
echo "   granting run.invoker to $CES_SERVICE_AGENT"
gcloud run services add-iam-policy-binding "$HYDRATION_SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" \
  --role roles/run.invoker --quiet >/dev/null
echo "   granted"

echo "   creating the OpenAPI toolset on $VOICE_APP"
"$PY" bootstrap/create_hydration_tool.py "$HYDRATION_URL"

# --- 4. attach the toolset and the firing callback ---------------------------
echo
echo "▶ [4/6] Attach hydration toolset + before_model callback to the root agent"
"$PY" bootstrap/attach_hydration.py

# --- 5. relay (public) -------------------------------------------------------
# The relay authenticates to CXAS as its Cloud Run runtime service account — the
# project's default compute SA, since we set none explicitly. Opening a bidi
# session needs ces.sessions.bidiRunSession, which lives in roles/ces.client and
# in NO dialogflow.* role.
#
# Why this grant is not optional: projects created recently do not auto-grant
# Editor to the default compute SA (org policy
# iam.automaticIamGrantsForDefaultServiceAccounts), so on a clean project that
# account starts with no roles. The deploy then succeeds, the page loads, and
# pressing Start does nothing — the CXAS socket is refused and the browser socket
# closes with no visible error. Older projects hide the problem because their
# default SA still carries Editor.
echo
echo "▶ [5/6] Relay → Cloud Run (public, warm, long-lived sockets)"
RELAY_SA="${RELAY_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
echo "   granting roles/ces.client to $RELAY_SA"
if gcloud projects add-iam-policy-binding "$PROJECT" \
     --member "serviceAccount:${RELAY_SA}" \
     --role roles/ces.client --condition=None --quiet >/dev/null 2>&1; then
  echo "   granted"
else
  echo "   ⚠ COULD NOT BIND roles/ces.client to ${RELAY_SA}."
  echo "     You need roles/resourcemanager.projectIamAdmin (or Owner) to do this."
  echo "     Without it the relay cannot open a CXAS session and Start will appear"
  echo "     to do nothing. Grant it by hand, then re-run:"
  echo "       gcloud projects add-iam-policy-binding $PROJECT \\"
  echo "         --member serviceAccount:${RELAY_SA} --role roles/ces.client"
fi

# --timeout is the cap on a single WebSocket, so it doubles as the max call
# length; 3600s is the Cloud Run ceiling.
gcloud run deploy "$RELAY_SERVICE" \
  --source . \
  --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 3600 \
  --min-instances 1 --max-instances "${RELAY_MAX_INSTANCES:-5}" \
  --cpu 2 --memory 1Gi \
  --cpu-boost \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOC}@VOICE_APP_ID=${VOICE_APP}" \
  --quiet

RELAY_URL="$(gcloud run services describe "$RELAY_SERVICE" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
# https -> wss: the page is served over TLS, and a secure page may not open an
# insecure ws:// socket (nor would the mic work off a secure context).
RELAY_WSS="wss://${RELAY_URL#https://}"
echo "   relay: $RELAY_URL"

# --- 6. UI (public), pointed at the relay ------------------------------------
# Order matters: the UI has to be told where the relay is, and it can only be told
# after the relay exists and has a URL.
echo
echo "▶ [6/6] UI → Cloud Run (public)"
printf 'window.RELAY_URL = "%s";\n' "$RELAY_WSS" > frontend/config.js
echo "   frontend/config.js -> $RELAY_WSS"

gcloud run deploy "$UI_SERVICE" \
  --source frontend \
  --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 300 \
  --min-instances 0 --max-instances 3 \
  --cpu 1 --memory 512Mi \
  --allow-unauthenticated \
  --quiet

UI_URL="$(gcloud run services describe "$UI_SERVICE" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"

# Local runs must not inherit the deployed relay URL — run_local.sh rewrites this
# file on every start, but leaving a wss:// pointer here is a confusing trap.
printf 'window.RELAY_URL = "ws://localhost:8000";\n' > frontend/config.js

# --- summary -----------------------------------------------------------------
echo
echo "══════════════════════════════════════════════════════════════════════════"
echo " DEPLOYED"
echo "══════════════════════════════════════════════════════════════════════════"
echo "  Web UI      : ${UI_URL}/chat.html      (public)"
echo "  Relay       : ${RELAY_URL}             (public)"
echo "  Hydration   : ${HYDRATION_URL}         (private, OIDC)"
echo "  Voice app   : ${VOICE_APP}   ·   Chat app: ${CHAT_APP}"
echo
echo "  Simulator   : open ${VOICE_APP} in the Conversational Agents console"
echo
echo "  Arm a cross-channel test — BOTH variables. customer_id is the GATE"
echo "  (empty = hydration never fires); resume_conversation_id is what loads:"
echo
echo "    $PY bootstrap/set_hydration_vars.py \\"
echo "        --customer-id cust-test --conversation-id <PRIOR_SESSION_UUID>"
echo
echo "  A prior conversation's UUID is the session id from an earlier run."
echo "  Then start a NEW session — expect a welcome-back naming their issue."
echo
echo "  Teardown    : bash destroy_all.sh          (Cloud Run services)"
echo "                bash destroy_all.sh --all    (also the CXAS apps)"
echo "══════════════════════════════════════════════════════════════════════════"
