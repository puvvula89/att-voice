#!/usr/bin/env bash
# Tear down everything deploy_all.sh created (Cloud Run services + Agent Engine
# + staging bucket). Config from .env. Safe to re-run; missing resources are skipped.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

if [[ -f .env ]]; then set -a; source .env; set +a; fi

: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT in .env}"
PROJECT="$GOOGLE_CLOUD_PROJECT"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
MCP_SERVICE="${MCP_SERVICE:-att-mcp-phone-upgrade}"
RELAY_SERVICE="${RELAY_SERVICE:-att-phone-upgrade-relay}"
UI_SERVICE="${UI_SERVICE:-att-phone-upgrade-ui}"
AE_STAGING_BUCKET="${AE_STAGING_BUCKET:-${PROJECT}-agent-engine}"
AGENT_DISPLAY_NAME="${AGENT_DISPLAY_NAME:-att-phone-upgrade-live}"
PY="$ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY="python"

echo "▶ Tearing down project=$PROJECT region=$REGION"

for svc in "$UI_SERVICE" "$RELAY_SERVICE" "$MCP_SERVICE"; do
  if gcloud run services delete "$svc" --region "$REGION" --project "$PROJECT" --quiet 2>/dev/null; then
    echo "   deleted Cloud Run $svc"
  else
    echo "   (skip Cloud Run $svc — not found)"
  fi
done

GOOGLE_CLOUD_PROJECT="$PROJECT" GOOGLE_CLOUD_LOCATION="$REGION" AGENT_DISPLAY_NAME="$AGENT_DISPLAY_NAME" "$PY" - <<'PYEOF'
import os, vertexai
c = vertexai.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
dn = os.environ.get("AGENT_DISPLAY_NAME")
found = False
for e in c.agent_engines.list():
    r = e.api_resource
    if getattr(r, "display_name", "") == dn:
        found = True
        try:
            c.agent_engines.delete(name=r.name, force=True)
            print("   deleted Agent Engine", r.name.split("/")[-1])
        except Exception as ex:
            print("   Agent Engine delete err:", str(ex)[:120])
if not found:
    print("   (skip Agent Engine — none named", dn, ")")
PYEOF

if gcloud storage rm -r "gs://$AE_STAGING_BUCKET" 2>/dev/null; then
  echo "   deleted bucket gs://$AE_STAGING_BUCKET"
else
  echo "   (skip bucket — not found/empty)"
fi

rm -f deploy/.engine_name
echo "✅ Teardown complete."
