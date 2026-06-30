"""Deploy the scope probe, run it inside the container, print the result, and
tear the engine down. Configure entirely via environment variables.

    GOOGLE_CLOUD_PROJECT      (required)  project to deploy into
    GOOGLE_CLOUD_LOCATION     (default us-central1)
    STAGING_BUCKET            (default <project>-agent-engine)
    RUNTIME_SERVICE_ACCOUNT   (optional)  run the engine AS this service account
                                          (set this to the SA your real agent uses)
    KEEP_ENGINE               (optional)  set to 1 to leave the engine deployed

Run:
    pip install -r requirements.txt          # from a Python 3.12 environment
    GOOGLE_CLOUD_PROJECT=my-proj \\
    RUNTIME_SERVICE_ACCOUNT=my-sa@my-proj.iam.gserviceaccount.com \\
    python deploy.py

IMPORTANT: deploy from Python 3.12. The Agent Engine container runs 3.12; the
agent is pickled on this host and unpickled in the container, so a mismatched
Python version produces a container that fails to start.
"""
import json
import os
import sys

import vertexai
from vertexai import types as vtypes

from agent import probe

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT:
    sys.exit("ERROR: set GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ.get("STAGING_BUCKET") or f"{PROJECT}-agent-engine"
RUNTIME_SA = os.environ.get("RUNTIME_SERVICE_ACCOUNT", "").strip()
KEEP = os.environ.get("KEEP_ENGINE", "").strip() == "1"

if sys.version_info[:2] != (3, 12):
    print(
        f"WARNING: deploying from Python {sys.version_info[0]}.{sys.version_info[1]}, "
        "but the container is 3.12. If the engine fails to start, redeploy from 3.12.",
        flush=True,
    )

kwargs = dict(
    display_name="scope-probe",
    description="Reports the runtime credential and attempts CreateSession in-container.",
    staging_bucket=f"gs://{BUCKET}",
    requirements=[
        # Pinned to MATCH the shared-session-voice-and-chat deploy exactly, so the
        # container resolves the same auth stack (google-auth / google-genai) the
        # real agent runs. google-adk==2.1.0 holds google-genai on the <2,>=1.72
        # line; cloudpickle==3.1.2 matches the pickling host. Do not pin genai
        # separately — let adk 2.1.0 resolve it. `requests` is for the probe only.
        "google-cloud-aiplatform[agent_engines]",
        "google-adk==2.1.0",
        "cloudpickle==3.1.2",
        "requests",
    ],
    extra_packages=["agent.py"],  # ship the probe module so the container can import it
    python_version="3.12",
)
if RUNTIME_SA:
    kwargs["identity_type"] = vtypes.IdentityType.SERVICE_ACCOUNT
    kwargs["service_account"] = RUNTIME_SA

client = vertexai.Client(project=PROJECT, location=LOCATION)
identity = f"custom SA: {RUNTIME_SA}" if RUNTIME_SA else "default managed identity"
print(
    f"Deploying scope-probe to {PROJECT}/{LOCATION}\n  identity: {identity}\n"
    "  (container build, usually a few minutes) ...",
    flush=True,
)

engine = client.agent_engines.create(agent=probe, config=vtypes.AgentEngineConfig(**kwargs))
name = engine.api_resource.name
print("DEPLOYED:", name, flush=True)

try:
    print("\n===== IN-CONTAINER PROBE OUTPUT =====", flush=True)
    result = client.agent_engines.get(name=name).query()
    print(json.dumps(result, indent=2), flush=True)
    print("=====================================", flush=True)
finally:
    if KEEP:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".engine_name")
        with open(path, "w") as f:
            f.write(name)
        print(f"\nKEEP_ENGINE=1 -> engine left deployed:\n  {name}", flush=True)
        print("Delete it later with:  python destroy.py", flush=True)
    else:
        print("\nTearing down ...", flush=True)
        client.agent_engines.delete(name=name, force=True)
        print("DESTROYED:", name, flush=True)
