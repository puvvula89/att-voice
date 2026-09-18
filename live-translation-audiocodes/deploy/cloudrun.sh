#!/usr/bin/env bash
# Deploy the bridge to Cloud Run, or tear it down again.
#
#   deploy/cloudrun.sh up       build, deploy, print the bot URL
#   deploy/cloudrun.sh logs     pull this run's events into recordings/ for the console
#   deploy/cloudrun.sh down     delete the service and the service account
#
# The console is deliberately NOT deployed. It reads the bridge's event files, and
# nothing may share the audio path -- the events already go to stdout, so `logs`
# pulls them out of Cloud Logging afterwards and the local console renders them.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

SERVICE=${SERVICE:-live-translation-bridge}
REGION=${REGION:-us-east4}
PROJECT=${GOOGLE_CLOUD_PROJECT}
SA_NAME=${SA_NAME:-live-translation-bridge}
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

case "${1:-}" in
up)
  if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "==> creating service account $SA"
    gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
      --display-name "Live translation bridge"
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member "serviceAccount:$SA" --role roles/aiplatform.user >/dev/null
  fi

  echo "==> deploying $SERVICE to $REGION"
  # --no-cpu-throttling keeps the event loop running between requests, which a
  # long-lived audio WebSocket depends on. max-instances=1 because the two call legs
  # are paired in process: a second instance would never see the first leg.
  gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" \
    --region "$REGION" \
    --service-account "$SA" \
    --allow-unauthenticated \
    --cpu 4 \
    --memory 2Gi \
    --cpu-boost \
    --no-cpu-throttling \
    --min-instances 1 \
    --max-instances 1 \
    --concurrency 20 \
    --timeout 3600 \
    --set-env-vars "^|^TRANSLATOR=${TRANSLATOR:-gemini}|GOOGLE_CLOUD_PROJECT=${PROJECT}|GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}|LIVE_TRANSLATE_MODEL=${LIVE_TRANSLATE_MODEL}|ANSWER_PROMPT=${ANSWER_PROMPT:-silence}|CALLER_LANGUAGE=${CALLER_LANGUAGE}|AGENT_MODE=${AGENT_MODE:-dialin}|ECHO_TO_AGENT=${ECHO_TO_AGENT:-false}|SERVE_CONSOLE=true|AUDIOCODES_TOKEN=${AUDIOCODES_TOKEN}"

  URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
        --format 'value(status.url)')
  echo
  echo "Service:   $URL"
  echo "Bot URL:   wss://${URL#https://}/audiocodes-ws"
  echo "Live call: $URL/console/"
  echo "Dashboard: $URL/console/dashboard"
  ;;

logs)
  # Rebuild recordings/<conv>/events.jsonl from the structured log lines so the
  # local console can open a cloud call by conversation ID.
  WINDOW=${2:-30m}
  echo "==> pulling the last $WINDOW of events"
  gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE} AND textPayload:\"\\\"conv\\\"\"" \
    --project "$PROJECT" --freshness "$WINDOW" --order asc --format 'value(textPayload)' \
  | sed 's/^.*\({"conv"\)/\1/' \
  | python3 -c '
import json, os, sys
seen = {}
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        continue
    conv = e.get("conv")
    if not conv:
        continue
    if conv not in seen:
        os.makedirs(os.path.join("recordings", conv), exist_ok=True)
        seen[conv] = open(os.path.join("recordings", conv, "events.jsonl"), "w", encoding="utf-8")
    seen[conv].write(json.dumps(e, ensure_ascii=False) + "\n")
for conv, f in seen.items():
    f.close()
    print("wrote recordings/%s/events.jsonl" % conv)
if not seen:
    print("no events found in that window")
'
  ;;

down)
  echo "==> deleting $SERVICE"
  gcloud run services delete "$SERVICE" --project "$PROJECT" --region "$REGION" --quiet || true
  echo "==> removing $SA"
  gcloud projects remove-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/aiplatform.user --quiet >/dev/null 2>&1 || true
  gcloud iam service-accounts delete "$SA" --project "$PROJECT" --quiet 2>/dev/null || true
  echo "done"
  ;;

*)
  echo "usage: $0 {up|logs [window]|down}" >&2
  exit 2
  ;;
esac
