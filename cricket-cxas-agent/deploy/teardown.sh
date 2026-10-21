#!/usr/bin/env bash
# Remove everything prep and deploy created. Asks first; pass --yes to skip the question.
#
# Kept: enabled APIs and the Firestore database itself (a project has one (default) database, and
# deleting it blocks re-creating it for a while); its collections are cleared instead.
. "$(dirname "$0")/common.sh"
APP_ID="${CARE_APP_ID:-cricket-care}"
LOC="${CXAS_LOCATION:-us}"

if [ "${1:-}" != "--yes" ]; then
  read -r -p "Delete app $APP_ID, service $SERVICE, data store ${DATASTORE_ID:-cricket-tutorials} and saved progress in $PROJECT? [y/N] " a
  [ "$a" = "y" ] || { echo "nothing deleted"; exit 0; }
fi

step "Agent app $APP_ID"
.venv/bin/cxas --no-input delete --app-name "projects/$PROJECT/locations/$LOC/apps/$APP_ID" --force || echo "not found"

step "Support server $SERVICE"
gcloud run services delete "$SERVICE" --region "$REGION" --project "$PROJECT" --quiet 2>/dev/null || echo "not found"

step "Data store"
$PY -m knowledge.load_datastore delete

step "Saved progress (and tutorials an earlier version kept in Firestore)"
$PY - <<PY
import os
from google.cloud import firestore
db = firestore.Client(project="$PROJECT", database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
for coll in ("progress", "tutorials", "devices", "meta"):
    n = 0
    for d in db.collection(coll).stream():
        d.reference.delete(); n += 1
    print(f"{coll}: deleted {n} documents")
PY

echo; echo "teardown done"
