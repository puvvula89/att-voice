#!/usr/bin/env bash
# Deploy the hydration service and wire it into CXAS as an OpenAPI tool.
#
#   bash hydration/deploy_hydration.sh
#
# Three steps:
#   1. Cloud Run (PRIVATE, warm, CPU-boosted) — the service that can actually
#      reach the CES API, since CXAS python tools have no network at all.
#   2. Grant run.invoker to the CES service agent so CXAS can call it over OIDC.
#   3. Create the OpenAPI toolset on the app, pointed at the service.
#
# LATENCY: this runs on the caller's FIRST turn, so a cold start would be heard
# as dead air. min-instances=1 keeps an instance resident, cpu-boost speeds the
# start it does pay, and cpu-throttling=off keeps the idle instance responsive
# instead of being throttled to near-zero between requests.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source .env; set +a

PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${HYDRATION_SERVICE:-cxas-hydration}"
APP_ID="${VOICE_APP_ID:-cxas-voice-and-chat}"
CXAS_LOC="${CXAS_LOCATION:-us}"

# CES service agent mints the OIDC token used to call the private service.
if [[ -z "${CES_SERVICE_AGENT:-}" ]]; then
  PNUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  CES_SERVICE_AGENT="service-${PNUM}@gcp-sa-ces.iam.gserviceaccount.com"
fi

echo "▶ [1/3] Deploy hydration service → Cloud Run (private, warm, boosted)"
gcloud run deploy "$SERVICE" \
  --source hydration \
  --region "$REGION" --project "$PROJECT" \
  --port 8080 --timeout 60 \
  --min-instances 1 \
  --max-instances "${HYDRATION_MAX_INSTANCES:-3}" \
  --cpu 2 --memory 1Gi \
  --cpu-boost \
  --no-cpu-throttling \
  --no-allow-unauthenticated \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOC}@VOICE_APP_ID=${APP_ID}" \
  --quiet

HYDRATION_URL="$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
echo "   url: $HYDRATION_URL"

echo "▶ [2/3] Grant run.invoker to CES service agent ($CES_SERVICE_AGENT)"
gcloud run services add-iam-policy-binding "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" \
  --role roles/run.invoker --quiet >/dev/null
echo "   granted"

echo "▶ [3/3] Create the OpenAPI toolset on $APP_ID"
PY="${PY:-../cxas-to-adk-a2a/.venv/bin/python}"
"$PY" bootstrap/create_hydration_tool.py "$HYDRATION_URL"

echo
echo "DONE."
echo "  service : $HYDRATION_URL  (private, OIDC, min-instances=1, cpu-boost)"
echo "  next    : attach the toolset + firing callback to the root agent —"
echo "              python bootstrap/attach_hydration.py"
echo "            then arm a test (BOTH variables; customer_id is the gate) —"
echo "              python bootstrap/set_hydration_vars.py \\"
echo "                  --customer-id cust-test --conversation-id <PRIOR_UUID>"
echo "            for GTP, also cut a version and repoint the channel (pinned)."
