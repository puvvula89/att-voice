#!/usr/bin/env bash
# S1 spike — deploy the one-tool MCP server privately and let the CES service
# agent invoke it. Prints the MCP URL to hand to create_toolset.py.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="../../.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE — copy .env.example and fill it in"; exit 1; }
set -a; . "$ENV_FILE"; set +a

PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${S1_SERVICE:-cricket-s1-mcp}"

echo "[1] deploying $SERVICE to $REGION in $PROJECT"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --project "$PROJECT" \
  --no-allow-unauthenticated --min-instances 0 --max-instances 2 \
  --quiet >/dev/null

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" \
        --project "$PROJECT" --format='value(status.url)')

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
CES_SERVICE_AGENT="${CES_SERVICE_AGENT:-service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com}"

echo "[2] granting run.invoker to $CES_SERVICE_AGENT"
gcloud run services add-iam-policy-binding "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --member "serviceAccount:${CES_SERVICE_AGENT}" \
  --role roles/run.invoker --quiet >/dev/null

echo
echo "MCP endpoint: ${URL}/mcp/"
echo "next: python bootstrap-less spike wiring —"
echo "  ../../.venv/bin/python create_toolset.py ${URL}/mcp/"
