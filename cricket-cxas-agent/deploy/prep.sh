#!/usr/bin/env bash
# Stage 1: everything the content and deploy stages need. Safe to re-run.
. "$(dirname "$0")/common.sh"

step "APIs in $PROJECT"
gcloud services enable ces.googleapis.com discoveryengine.googleapis.com firestore.googleapis.com \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com \
  --project "$PROJECT"

step "Agent platform service agent (granted access to the support server at deploy)"
gcloud beta services identity create --service=ces.googleapis.com --project "$PROJECT" >/dev/null

step "Firestore (default) database, Native mode"
if gcloud firestore databases describe --database="${FIRESTORE_DATABASE:-(default)}" --project "$PROJECT" >/dev/null 2>&1; then
  echo "exists"
else
  gcloud firestore databases create --database="${FIRESTORE_DATABASE:-(default)}" \
    --location="${FIRESTORE_LOCATION:-nam5}" --type=firestore-native --project "$PROJECT"
fi

step "Python environment"
[ -x "$PY" ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

step "Agent Search data store"
$PY -m knowledge.load_datastore create

echo; echo "prep done. next: deploy/content.sh"
