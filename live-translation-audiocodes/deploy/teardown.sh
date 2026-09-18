#!/usr/bin/env bash
# Remove everything this POC created in a Google Cloud project, so it stops costing
# anything.
#
#   deploy/teardown.sh           show what exists and what would be deleted
#   deploy/teardown.sh --yes     delete it
#
# `cloudrun.sh down` only removes the service and its service account. Deploying
# with `--source` also pushes a container image per deploy into Artifact Registry
# and leaves build artifacts in a staging bucket; both are billed for storage after
# the service is gone, which is why they are cleaned up here too.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f ./.env ]; then
  echo "No .env here, so there is nothing to read the project from." >&2
  exit 1
fi
set -a; . ./.env; set +a

PROJECT=${GOOGLE_CLOUD_PROJECT:-}
[ -n "$PROJECT" ] || { echo "GOOGLE_CLOUD_PROJECT is not set in .env" >&2; exit 1; }

SERVICE=${SERVICE:-live-translation-bridge}
REGION=${REGION:-us-east4}
SA_NAME=${SA_NAME:-live-translation-bridge}
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
# Created automatically by `gcloud run deploy --source`, one image per deploy.
AR_REPO="cloud-run-source-deploy"

APPLY=false
[ "${1:-}" = "--yes" ] && APPLY=true

command -v gcloud >/dev/null || { echo "gcloud is not installed." >&2; exit 1; }

echo "project: $PROJECT"
echo "region:  $REGION"
echo

found=false

have_service=false
if gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
     >/dev/null 2>&1; then
  have_service=true; found=true
  echo "  Cloud Run service   $SERVICE"
fi

have_repo=false
if gcloud artifacts repositories describe "$AR_REPO" --project "$PROJECT" \
     --location "$REGION" >/dev/null 2>&1; then
  have_repo=true; found=true
  # Size is what actually costs money here, so show it rather than a bare name.
  images=$(gcloud artifacts docker images list \
    "${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}" --project "$PROJECT" \
    --format='value(IMAGE)' 2>/dev/null | wc -l | tr -d ' ')
  echo "  Artifact Registry   $AR_REPO (${images} image(s), billed for storage)"
fi

have_sa=false
if gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
  have_sa=true; found=true
  echo "  Service account     $SA"
fi

if [ "$found" = false ]; then
  echo "Nothing left to remove."
  exit 0
fi

if [ "$APPLY" = false ]; then
  echo
  echo "Nothing deleted. Re-run with --yes to remove the above."
  exit 0
fi

echo
if [ "$have_service" = true ]; then
  echo "==> deleting Cloud Run service $SERVICE"
  gcloud run services delete "$SERVICE" --project "$PROJECT" --region "$REGION" --quiet
fi

if [ "$have_repo" = true ]; then
  echo "==> deleting Artifact Registry repo $AR_REPO"
  gcloud artifacts repositories delete "$AR_REPO" --project "$PROJECT" \
    --location "$REGION" --quiet
fi

if [ "$have_sa" = true ]; then
  echo "==> removing IAM binding and service account $SA"
  gcloud projects remove-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/aiplatform.user \
    --condition=None --quiet >/dev/null 2>&1 || true
  gcloud iam service-accounts delete "$SA" --project "$PROJECT" --quiet
fi

# Cloud Build stages sources in a regional bucket. Only this service's objects are
# removed -- the bucket is shared with anything else built in the project.
BUCKET="gs://${PROJECT}_cloudbuild"
if gcloud storage ls "$BUCKET" >/dev/null 2>&1; then
  echo "==> clearing build staging objects in $BUCKET"
  gcloud storage rm "${BUCKET}/source/**" --quiet >/dev/null 2>&1 || true
fi

echo
echo "==> verifying"
left=false
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  >/dev/null 2>&1 && { echo "  STILL PRESENT: service $SERVICE"; left=true; }
gcloud artifacts repositories describe "$AR_REPO" --project "$PROJECT" \
  --location "$REGION" >/dev/null 2>&1 && { echo "  STILL PRESENT: repo $AR_REPO"; left=true; }
gcloud iam service-accounts describe "$SA" --project "$PROJECT" \
  >/dev/null 2>&1 && { echo "  STILL PRESENT: $SA"; left=true; }

if [ "$left" = true ]; then
  echo "Some resources remain -- check the messages above." >&2
  exit 1
fi
echo "  all clear -- nothing billable left from this POC"
echo
echo "The enabled APIs are left alone: they cost nothing on their own and other"
echo "work in this project may rely on them."
