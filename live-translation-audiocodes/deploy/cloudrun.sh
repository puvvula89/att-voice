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

if [ ! -f ./.env ]; then
  echo "No .env here. Copy the template and fill in the four required values:" >&2
  echo "    cp .env.example .env" >&2
  exit 1
fi
set -a; . ./.env; set +a

# Checked explicitly rather than left to `set -u`, which would fail later with an
# unbound-variable trace that says nothing about what to do.
missing=""
for var in GOOGLE_CLOUD_PROJECT AUDIOCODES_TOKEN CALLER_LANGUAGE; do
  [ -n "${!var:-}" ] || missing="$missing $var"
done
if [ -n "$missing" ]; then
  echo "Set these in .env before deploying:$missing" >&2
  exit 1
fi

SERVICE=${SERVICE:-live-translation-bridge}
REGION=${REGION:-us-east4}
PROJECT=${GOOGLE_CLOUD_PROJECT}
SA_NAME=${SA_NAME:-live-translation-bridge}
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

case "${1:-}" in
up)
  command -v gcloud >/dev/null || { echo "gcloud is not installed." >&2; exit 1; }
  gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . \
    || { echo "Not signed in. Run: gcloud auth login" >&2; exit 1; }
  gcloud projects describe "$PROJECT" >/dev/null 2>&1 \
    || { echo "Cannot see project '$PROJECT'. Check the ID and your access." >&2; exit 1; }

  # Enabling is idempotent and takes seconds on a project that already has them.
  echo "==> enabling required APIs on $PROJECT"
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com aiplatform.googleapis.com --project "$PROJECT"

  # `run deploy --source` builds through Cloud Build, which runs as the Compute
  # Engine default service account. On a project where that account has never built
  # anything the build fails on storage/logging permissions, so grant the builder
  # role up front rather than leaving a first deploy to fail confusingly.
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
  BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$BUILD_SA" --role roles/cloudbuild.builds.builder \
    --condition=None >/dev/null 2>&1 || true

  if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
    echo "==> creating service account $SA"
    gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
      --display-name "Live translation bridge"
  fi
  # Re-applied every deploy: harmless when already bound, and it repairs a project
  # where the binding was removed without the account being deleted.
  #
  # Retried because a freshly created service account is not immediately visible to
  # the IAM policy API -- binding it straight away fails with "does not exist" even
  # though the create succeeded. It settles within a few seconds.
  echo "==> granting roles/aiplatform.user to $SA_NAME"
  for attempt in 1 2 3 4 5 6; do
    if gcloud projects add-iam-policy-binding "$PROJECT" \
         --member "serviceAccount:$SA" --role roles/aiplatform.user \
         --condition=None >/dev/null 2>&1; then
      break
    fi
    if [ "$attempt" = 6 ]; then
      echo "Could not grant roles/aiplatform.user to $SA after several tries." >&2
      echo "Wait a moment and re-run; the service account exists already." >&2
      exit 1
    fi
    sleep 5
  done

  # Created up front because `run deploy --source` otherwise stops to ask whether it
  # may create it, which hangs anything running unattended. Same name and region the
  # prompt would have used, so teardown still finds it.
  if ! gcloud artifacts repositories describe cloud-run-source-deploy \
       --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    echo "==> creating Artifact Registry repo cloud-run-source-deploy"
    gcloud artifacts repositories create cloud-run-source-deploy \
      --project "$PROJECT" --location "$REGION" --repository-format docker \
      --description "Containers built by cloudrun.sh" >/dev/null
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
    --set-env-vars "^|^TRANSLATOR=${TRANSLATOR:-gemini}|GOOGLE_CLOUD_PROJECT=${PROJECT}|GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}|LIVE_TRANSLATE_MODEL=${LIVE_TRANSLATE_MODEL:-gemini-3.5-live-translate-preview}|ANSWER_PROMPT=${ANSWER_PROMPT:-silence}|CALLER_LANGUAGE=${CALLER_LANGUAGE}|AGENT_MODE=${AGENT_MODE:-dialin}|ECHO_TO_AGENT=${ECHO_TO_AGENT:-false}|SERVE_CONSOLE=true|AUDIOCODES_TOKEN=${AUDIOCODES_TOKEN}"

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
