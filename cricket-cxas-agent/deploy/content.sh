#!/usr/bin/env bash
# Stage 2 (runs locally): tutorials → labels → catalog → step pictures bucket → Agent Search data store.
#
#   deploy/content.sh            build from the committed raw tutorials and load them
#   deploy/content.sh --scrape   re-scrape every device in knowledge/raw first (headless browser, ~1 h)
#
# Labels are cached per tutorial, so only new or changed tutorials go to Gemini. Hand-reviewed call
# risk in knowledge/step_review.json is applied on top; the build prints any entry that no longer matches.
. "$(dirname "$0")/common.sh"

if [ "${1:-}" = "--scrape" ]; then
  step "Scrape (OS version per device is read from its current raw file)"
  .venv/bin/pip install -q playwright && .venv/bin/python -m playwright install chromium
  for f in knowledge/raw/*.json; do
    device=$(basename "$f" .json)
    osv=$($PY -c "import json,sys; print(next(iter(json.load(open(sys.argv[1])).values()))['os'])" "$f")
    echo "-- $device $osv"
    (cd knowledge/extract && ../../$PY extract.py extract "$device" "$osv" all)
  done
fi

step "Gemini labels (cached; 2 workers keep under the rate limit)"
$PY -m knowledge.enrich --workers 2

step "Build the catalog"
$PY -m knowledge.build_catalog

step "Copy step pictures into the private images bucket (only new ones)"
gcloud storage buckets describe "gs://${IMAGES_BUCKET}" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://${IMAGES_BUCKET}" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention --quiet
IMAGES_BUCKET="$IMAGES_BUCKET" $PY -m knowledge.images sync

step "Load the data store"
$PY -m knowledge.load_datastore load

echo; echo "content done. next: deploy/deploy.sh"
