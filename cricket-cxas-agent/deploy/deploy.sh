#!/usr/bin/env bash
# Stage 3: the support server on Cloud Run, then the agent app with SCRAPI, then the tests. Safe to re-run.
#
#   deploy/deploy.sh             deploy everything and run the tests
#   deploy/deploy.sh --no-test   deploy only
#
# One server instance, always warm: the demo account store is in-process, so a second instance would
# mean a second, divergent demo state.
. "$(dirname "$0")/common.sh"
APP_ID="${CARE_APP_ID:-cricket-care}"
LOC="${CXAS_LOCATION:-us}"
APP="projects/${PROJECT}/locations/${LOC}/apps/${APP_ID}"
CXAS=.venv/bin/cxas

TWILIO_ENV=""
if [ -n "${TWILIO_ACCOUNT_SID:-}" ] && [ -n "${TWILIO_AUTH_TOKEN:-}" ] && [ -n "${TWILIO_FROM:-}" ]; then
  TWILIO_ENV="|TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}|TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}|TWILIO_FROM=${TWILIO_FROM}|DEMO_SMS_NUMBER=${DEMO_SMS_NUMBER:-}"
fi

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

step "Agent app $APP_ID: build app/ for this project"
# app/ is the agent as SCRAPI files. Two values differ per project: the data store (environment.json,
# which push resolves) and the support server's URL (the platform does not resolve a toolset URL from
# environment.json, so it is written into the build copy).
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
cp -R app "$BUILD/Cricket_Care"
sed -i.bak "s|SUPPORT_MCP_URL|${URL}/mcp|" "$BUILD/Cricket_Care/toolsets/support/support.json"
rm "$BUILD/Cricket_Care/toolsets/support/support.json.bak"
DATASTORE="projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/dataStores/${DATASTORE_ID:-cricket-tutorials}"
cat > "$BUILD/environment.json" <<JSON
{"tools": {"search_tutorials": {"dataStoreTool": {"dataStoreSource": {"dataStore": {"name": "${DATASTORE}"}}}}}}
JSON
$CXAS lint --app-dir "$BUILD/Cricket_Care"

step "Agent app $APP_ID: create if missing (the voice model can only be set at creation), then push"
$PY - "$PROJECT" "$LOC" "$APP_ID" <<'PY'
import json, sys
from cxas_scrapi.core.apps import Apps
project, loc, app_id = sys.argv[1:]
apps = Apps(project_id=project, location=loc)
name = f"projects/{project}/locations/{loc}/apps/{app_id}"
if any(a.name == name for a in apps.list_apps()):
    print("exists", name)
else:
    cfg = json.load(open("app/app.json"))
    apps.create_app(app_id, cfg["displayName"], model_settings={"model": cfg["modelSettings"]["model"]})
    print("created", name)
PY
$CXAS push --app-dir "$BUILD/Cricket_Care" --env-file "$BUILD/environment.json" --to "$APP" --overwrite

if [ "${1:-}" != "--no-test" ]; then
  step "Tests"
  $PY bootstrap/run_turn_tests.py
fi

echo; echo "deployed. voice: RUNBOOK.md, 'Voice'. tear down: deploy/teardown.sh"
