#!/usr/bin/env bash
# Stage 3: the support server on Cloud Run, then the agent app, then the typed suite. Safe to re-run.
#
#   deploy/deploy.sh             deploy everything and run the suite
#   deploy/deploy.sh --no-test   deploy only
#
# One server instance, always warm: the demo account store is in-process, so a second instance would
# mean a second, divergent demo state.
. "$(dirname "$0")/common.sh"
APP_ID="${CARE_APP_ID:-cricket-care}"

TWILIO_ENV=""
if [ -n "${TWILIO_ACCOUNT_SID:-}" ] && [ -n "${TWILIO_AUTH_TOKEN:-}" ] && [ -n "${TWILIO_FROM:-}" ]; then
  TWILIO_ENV="|TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}|TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}|TWILIO_FROM=${TWILIO_FROM}|DEMO_SMS_NUMBER=${DEMO_SMS_NUMBER:-}"
fi

step "Agent app $APP_ID (agents, search and step tools, variables, callbacks)"
$PY bootstrap/create_app.py

step "Support server $SERVICE in $REGION"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --project "$PROJECT" \
  --no-allow-unauthenticated --min-instances 1 --max-instances 1 \
  --set-env-vars "^|^DEMO_PROFILE=${DEMO_PROFILE:-P3}|DEMO_CUSTOMER_ID=${DEMO_CUSTOMER_ID:-cust_2001}|MCP_WIRE_LOG=${MCP_WIRE_LOG:-0}|PROGRESS_BACKEND=firestore|GOOGLE_CLOUD_PROJECT=${PROJECT}|FIRESTORE_DATABASE=${FIRESTORE_DATABASE:-(default)}|RESUME_WINDOW_MINUTES=${RESUME_WINDOW_MINUTES:-30}${TWILIO_ENV}" \
  --quiet >/dev/null
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')
RUNTIME_SA=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
               --format='value(spec.template.spec.serviceAccountName)')
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
CES_SA="${CES_SERVICE_AGENT:-service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com}"

step "Access: the server uses Firestore; the agent platform calls the server"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${RUNTIME_SA}" \
  --role roles/datastore.user --condition=None --quiet >/dev/null
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --member "serviceAccount:${CES_SA}" --role roles/run.invoker --quiet >/dev/null

step "Connect the agent to the server"
$PY bootstrap/attach_support_toolset.py "${URL}/mcp"

if [ "${1:-}" != "--no-test" ]; then
  step "Typed suite"
  $PY bootstrap/run_suite.py
fi

echo; echo "deployed. voice: RUNBOOK.md, 'Voice'. tear down: deploy/teardown.sh"
