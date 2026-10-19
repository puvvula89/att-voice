#!/usr/bin/env bash
# Deploy the support MCP server privately to Cloud Run and let the CES service
# agent invoke it. Prints the MCP URL to hand to bootstrap/attach_support_toolset.py.
#
# One instance, always warm: the account store is in-process, so a second
# instance would mean a second, divergent demo state.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE — copy .env.example and fill it in"; exit 1; }
set -a; . "./$ENV_FILE"; set +a

PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SUPPORT_MCP_SERVICE:-cricket-support-mcp}"
PROFILE="${DEMO_PROFILE:-P3}"
# Forward Twilio credentials and the demo destination number only when all three
# credentials are set; the server treats a partial set as "not configured".
TWILIO_ENV=""
if [ -n "${TWILIO_ACCOUNT_SID:-}" ] && [ -n "${TWILIO_AUTH_TOKEN:-}" ] && [ -n "${TWILIO_FROM:-}" ]; then
  TWILIO_ENV="|TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}|TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}|TWILIO_FROM=${TWILIO_FROM}|DEMO_SMS_NUMBER=${DEMO_SMS_NUMBER:-}"
fi

echo "[1] deploying $SERVICE to $REGION in $PROJECT (profile $PROFILE)"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --project "$PROJECT" \
  --no-allow-unauthenticated --min-instances 1 --max-instances 1 \
  --set-env-vars "^|^DEMO_PROFILE=${PROFILE}|MCP_WIRE_LOG=${MCP_WIRE_LOG:-0}|CONTENT_BACKEND=firestore|GOOGLE_CLOUD_PROJECT=${PROJECT}|RESUME_WINDOW_MINUTES=${RESUME_WINDOW_MINUTES:-30}${TWILIO_ENV}" \
  --quiet >/dev/null

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" \
        --project "$PROJECT" --format='value(status.url)')

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
CES_SERVICE_AGENT="${CES_SERVICE_AGENT:-service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com}"

RUNTIME_SA=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
               --format='value(spec.template.spec.serviceAccountName)')
echo "[2] granting Firestore access to $RUNTIME_SA"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${RUNTIME_SA}" \
  --role roles/datastore.user --condition=None --quiet >/dev/null

echo "[3] granting run.invoker to $CES_SERVICE_AGENT"
gcloud run services add-iam-policy-binding "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" \
  --role roles/run.invoker --quiet >/dev/null

echo
echo "MCP endpoint: ${URL}/mcp"
echo "next: .venv/bin/python bootstrap/attach_support_toolset.py ${URL}/mcp"
