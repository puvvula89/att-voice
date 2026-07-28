#!/usr/bin/env bash
# One command, whole stack. Deploys every component of this bundle in dependency
# order and prints the live URLs at the end.
#
#   bash deploy_all.sh
#
# Six steps. Expect ~10-15 minutes, nearly all of it Cloud Build compiling the
# three container images.
#
#   1  chat app       (CX Agent Studio)      — created only if missing
#   2  voice app      (CX Agent Studio)      — created only if missing
#   3  hydration      Cloud Run (private)  + run.invoker + OpenAPI toolset
#   4  attach         hydration toolset + firing callback on the root agent
#   5  relay + UI     Cloud Run (PUBLIC)
#   6  summary        URLs and the arm-a-test command
#
# ⚠️ RUN THIS YOURSELF, INTERACTIVELY. Step 3 binds an IAM policy (run.invoker on
#    the hydration service); an unattended shell may be refused the binding.
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
export PY

echo "project=$PROJECT  region=$REGION  cxas_location=$CXAS_LOC"
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

# --- 3. hydration service + IAM + toolset ------------------------------------
echo
echo "▶ [3/6] Hydration service (Cloud Run private) + run.invoker + toolset"
bash hydration/deploy_hydration.sh

# --- 4. attach the toolset and the firing callback ---------------------------
echo
echo "▶ [4/6] Attach hydration toolset + before_model callback to the root agent"
"$PY" bootstrap/attach_hydration.py

# --- 5. public web surface ---------------------------------------------------
echo
echo "▶ [5/6] Relay + UI (Cloud Run, PUBLIC)"
bash deploy_web.sh

# --- 6. summary --------------------------------------------------------------
HYDRATION_URL="$(gcloud run services describe "${HYDRATION_SERVICE:-cxas-hydration}" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)' 2>/dev/null || true)"
RELAY_URL="$(gcloud run services describe "${RELAY_SERVICE:-cxas-web-relay}" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)' 2>/dev/null || true)"
UI_URL="$(gcloud run services describe "${UI_SERVICE:-cxas-web-ui}" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)' 2>/dev/null || true)"

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
