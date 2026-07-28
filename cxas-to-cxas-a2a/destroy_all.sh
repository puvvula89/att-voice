#!/usr/bin/env bash
# Remove everything deploy_all.sh created. The inverse, in reverse order.
#
#   bash destroy_all.sh              # Cloud Run services only (keeps the CXAS apps)
#   bash destroy_all.sh --all        # also delete both CX Agent Studio apps
#   bash destroy_all.sh --all --yes  # no confirmation prompt
#
# DEFAULT IS THE SAFE ONE. Deleting a CX Agent Studio app destroys its agents,
# its toolsets, AND its conversation history — the very history hydration reads.
# That is rarely what you want between test runs, so it takes an explicit --all.
#
#   default   1  UI            Cloud Run: cxas-web-ui        (public)
#             2  relay         Cloud Run: cxas-web-relay     (public)
#             3  hydration     Cloud Run: cxas-hydration     (private)
#   --all     4  hydration toolset + session variables
#             5  voice app     CX Agent Studio  ← destroys conversation history
#             6  chat app      CX Agent Studio
#
# Safe to re-run: anything already gone is skipped.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "ERROR: no .env here — cannot tell which project to clean up." >&2
  exit 1
fi
set -a; source .env; set +a

DELETE_APPS=false
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --all) DELETE_APPS=true ;;
    --yes|-y) ASSUME_YES=true ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

PROJECT="${CXAS_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
CXAS_LOC="${CXAS_LOCATION:-us}"
VOICE_APP="${VOICE_APP_ID:-cxas-voice-and-chat}"
CHAT_APP="${CHAT_APP_ID:-cxas-chat}"

if [[ -z "$PROJECT" ]]; then
  echo "ERROR: set CXAS_PROJECT (or GOOGLE_CLOUD_PROJECT) in .env" >&2
  exit 1
fi

echo "project=$PROJECT  region=$REGION"
echo "about to delete:"
echo "  Cloud Run : ${UI_SERVICE:-cxas-web-ui}, ${RELAY_SERVICE:-cxas-web-relay}, ${HYDRATION_SERVICE:-cxas-hydration}"
if $DELETE_APPS; then
  echo "  CXAS apps : $VOICE_APP, $CHAT_APP   ← INCLUDING ALL CONVERSATION HISTORY"
else
  echo "  CXAS apps : kept (pass --all to delete them too)"
fi
echo

if ! $ASSUME_YES; then
  read -r -p "Proceed? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "aborted"; exit 0; }
  echo
fi

# --- 1-3. Cloud Run services -------------------------------------------------
for service in "${UI_SERVICE:-cxas-web-ui}" \
               "${RELAY_SERVICE:-cxas-web-relay}" \
               "${HYDRATION_SERVICE:-cxas-hydration}"; do
  echo "▶ deleting Cloud Run service: $service"
  if gcloud run services delete "$service" \
       --region "$REGION" --project "$PROJECT" --quiet 2>/dev/null; then
    echo "   deleted"
  else
    echo "   (not present)"
  fi
done

if ! $DELETE_APPS; then
  echo
  echo "DONE — Cloud Run services removed. CXAS apps kept."
  echo "The hydration toolset still points at a service that no longer exists;"
  echo "re-run deploy_all.sh to restore it, or use --all to remove it too."
  exit 0
fi

# --- interpreter for the CXAS API calls --------------------------------------
if [[ -z "${PY:-}" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=".venv/bin/python"; else
    echo "ERROR: no .venv/bin/python. Run deploy_all.sh first, or set PY=..." >&2
    exit 1
  fi
fi
PY="$(cd "$(dirname "$PY")" && pwd)/$(basename "$PY")"

# --- 4-6. Toolset, variables, then the apps themselves -----------------------
echo
echo "▶ deleting CXAS toolset, variables, and apps"
"$PY" - "$VOICE_APP" "$CHAT_APP" <<'PYEOF'
import os
import sys

from dotenv import load_dotenv

load_dotenv(".env")

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.variables import Variables

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
voice_app_id, chat_app_id = sys.argv[1], sys.argv[2]
voice_app = f"projects/{PROJECT}/locations/{LOCATION}/apps/{voice_app_id}"

# Toolset first: deleting the app removes it anyway, but doing it explicitly
# keeps the teardown meaningful if you later choose to keep the app.
try:
    Agents(app_name=voice_app).client.delete_toolset(
        request=T.DeleteToolsetRequest(name=f"{voice_app}/toolsets/hydration", force=True))
    print("   toolset hydration: deleted")
except Exception as e:
    print(f"   toolset hydration: (not present — {type(e).__name__})")

for name in ("customer_id", "resume_conversation_id", "hydrated"):
    try:
        Variables(app_name=voice_app).delete_variable(variable_name=name)
        print(f"   variable {name}: deleted")
    except Exception as e:
        print(f"   variable {name}: (not present — {type(e).__name__})")

for app_id in (voice_app_id, chat_app_id):
    app_name = f"projects/{PROJECT}/locations/{LOCATION}/apps/{app_id}"
    try:
        Variables(app_name=app_name).delete_app(app_name)
        print(f"   app {app_id}: deleted")
    except Exception as e:
        print(f"   app {app_id}: (not present or not deleted — "
              f"{type(e).__name__}: {str(e)[:100]})")
PYEOF

echo
echo "DONE — all resources removed."
echo "Re-create everything with: bash deploy_all.sh"
