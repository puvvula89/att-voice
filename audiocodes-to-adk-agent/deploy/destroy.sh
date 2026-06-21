#!/usr/bin/env bash
set -euo pipefail
: "${GOOGLE_CLOUD_PROJECT:?}"; : "${GOOGLE_CLOUD_LOCATION:=us-central1}"
python - <<'PY'
import os, vertexai
c = vertexai.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
for e in c.agent_engines.list():
    if getattr(e.api_resource, "display_name", "") == "att-steering-adk":
        print("deleting", e.api_resource.name)
        c.agent_engines.delete(name=e.api_resource.name, force=True)
PY
