#!/usr/bin/env bash
# Tear down everything deploy_all.sh created: Cloud Run services (UI, relay, MCP,
# adapter), both Agent Engines, the CXAS steering app, and the staging bucket.
# Config from .env. Safe to re-run; missing resources are skipped.
set -uo pipefail

# Bundle root is the parent of deploy/ — all relative paths below resolve from there.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
MCP_SERVICE="${MCP_SERVICE:-att-mcp-phone-upgrade}"
RELAY_SERVICE="${RELAY_SERVICE:-att-phone-upgrade-relay}"
UI_SERVICE="${UI_SERVICE:-att-phone-upgrade-ui}"
ADAPTER_SERVICE="${ADAPTER_SERVICE:-att-cxas-adapter}"
AE_STAGING_BUCKET="${AE_STAGING_BUCKET:-${PROJECT}-agent-engine}"
AGENT_DISPLAY_NAME="${AGENT_DISPLAY_NAME:-att-phone-upgrade-live}"
CHAT_DISPLAY_NAME="${CHAT_DISPLAY_NAME:-att-phone-upgrade-chat}"
CXAS_PROJECT="${CXAS_PROJECT:-$PROJECT}"
CXAS_LOCATION="${CXAS_LOCATION:-us}"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="python"

echo "▶ Tearing down project=$PROJECT region=$REGION"

# 1. Cloud Run services.
for svc in "$UI_SERVICE" "$RELAY_SERVICE" "$MCP_SERVICE" "$ADAPTER_SERVICE"; do
  if gcloud run services delete "$svc" --region "$REGION" --project "$PROJECT" --quiet 2>/dev/null; then
    echo "   deleted Cloud Run $svc"
  else
    echo "   (skip Cloud Run $svc — not found)"
  fi
done

# 2. Agent Engines (by display name).
GOOGLE_CLOUD_PROJECT="$PROJECT" GOOGLE_CLOUD_LOCATION="$REGION" AGENT_DISPLAY_NAME="$AGENT_DISPLAY_NAME" CHAT_DISPLAY_NAME="$CHAT_DISPLAY_NAME" "$PY" - <<'PYEOF'
import os, vertexai
c = vertexai.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
targets = {os.environ.get("AGENT_DISPLAY_NAME"), os.environ.get("CHAT_DISPLAY_NAME")}
found = False
for e in c.agent_engines.list():
    r = e.api_resource
    if getattr(r, "display_name", "") in targets:
        found = True
        try:
            c.agent_engines.delete(name=r.name, force=True)
            print("   deleted Agent Engine", getattr(r, "display_name", ""), r.name.split("/")[-1])
        except Exception as ex:
            print("   Agent Engine delete err:", str(ex)[:120])
if not found:
    print("   (skip Agent Engine — none named", targets, ")")
PYEOF

# 3. CXAS steering app (Conversational Agents, location 'us').
CXAS_PROJECT="$CXAS_PROJECT" CXAS_LOCATION="$CXAS_LOCATION" "$PY" - <<'PYEOF'
import os
from cxas_scrapi.core.apps import Apps
proj = os.environ["CXAS_PROJECT"]; loc = os.environ["CXAS_LOCATION"]
app = f"projects/{proj}/locations/{loc}/apps/att-ivr-steering"
try:
    Apps(project_id=proj, location=loc).delete_app(app_name=app, force=True)
    print("   deleted CXAS app att-ivr-steering")
except Exception as ex:
    print("   (skip CXAS app — ", str(ex)[:100], ")")
PYEOF

# 4. Staging bucket.
if gcloud storage rm -r "gs://$AE_STAGING_BUCKET" 2>/dev/null; then
  echo "   deleted bucket gs://$AE_STAGING_BUCKET"
else
  echo "   (skip bucket — not found/empty)"
fi

rm -f deploy/.engine_name deploy/.chat_engine_name
echo "✅ Teardown complete."
