#!/usr/bin/env bash
# Deploy the unified voice+chat client — relay + static UI — to Cloud Run.
#
#   bash deploy_web.sh
#
# Order matters: the UI has to be told where the relay is, and it can only be
# told after the relay exists and has a URL. So we deploy the relay, read its
# URL back, write frontend/config.js, then deploy the UI.
#
# ⚠️ BOTH SERVICES ARE PUBLIC (allUsers). A browser cannot attach an OIDC token
#    to a WebSocket handshake, so a private relay is not reachable from a web
#    page — public is the only shape that lets you just open a URL and talk. That
#    means anyone with the link can drive your CXAS app and spend its quota. This
#    is a demo posture, not a production one: tear it down when you are done
#    (see destroy_all.sh), and remember the app already 429s under light load.
#
# WEBSOCKETS ON CLOUD RUN: --timeout is the cap on a single connection, so it
# doubles as the max call length; 3600s is the ceiling. min-instances=1 keeps a
# warm instance so the first turn is not a cold start, and cpu-boost speeds the
# start it does pay.
set -euo pipefail
cd "$(dirname "$0")"

set -a; source .env; set +a

PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
RELAY_SERVICE="${RELAY_SERVICE:-cxas-web-relay}"
UI_SERVICE="${UI_SERVICE:-cxas-web-ui}"
APP_ID="${VOICE_APP_ID:-cxas-voice-and-chat}"
CXAS_LOC="${CXAS_LOCATION:-us}"

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
echo "▶ [0/3] Grant roles/ces.client to the relay's runtime service account"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
RELAY_SA="${RELAY_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
if gcloud projects add-iam-policy-binding "$PROJECT" \
     --member "serviceAccount:${RELAY_SA}" \
     --role roles/ces.client --condition=None --quiet >/dev/null 2>&1; then
  echo "   granted to ${RELAY_SA}"
else
  echo "   ⚠ COULD NOT BIND roles/ces.client to ${RELAY_SA}."
  echo "     You need roles/resourcemanager.projectIamAdmin (or Owner) to do this."
  echo "     Without it the relay cannot open a CXAS session and Start will appear"
  echo "     to do nothing. Grant it by hand, then re-run:"
  echo "       gcloud projects add-iam-policy-binding $PROJECT \\"
  echo "         --member serviceAccount:${RELAY_SA} --role roles/ces.client"
fi

echo "▶ [1/3] Deploy relay → Cloud Run (public, warm, long-lived sockets)"
gcloud run deploy "$RELAY_SERVICE" \
  --source . \
  --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 3600 \
  --min-instances 1 --max-instances "${RELAY_MAX_INSTANCES:-5}" \
  --cpu 2 --memory 1Gi \
  --cpu-boost \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOC}@VOICE_APP_ID=${APP_ID}" \
  --quiet

RELAY_URL="$(gcloud run services describe "$RELAY_SERVICE" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
# https -> wss: the page is served over TLS, and a secure page may not open an
# insecure ws:// socket (nor would the mic work off a secure context).
RELAY_WSS="wss://${RELAY_URL#https://}"
echo "   relay: $RELAY_URL"

echo "▶ [2/3] Point the UI at the deployed relay"
printf 'window.RELAY_URL = "%s";\n' "$RELAY_WSS" > frontend/config.js
echo "   frontend/config.js -> $RELAY_WSS"

echo "▶ [3/3] Deploy UI → Cloud Run (public)"
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

echo
echo "DONE."
echo "  UI    : ${UI_URL}/chat.html"
echo "  relay : ${RELAY_URL}  (${RELAY_WSS})"
echo
echo "  Both are PUBLIC. Tear down with: bash destroy_all.sh"
