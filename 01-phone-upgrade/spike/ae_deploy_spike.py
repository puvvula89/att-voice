"""Deploy the minimal bidi spike app to Agent Engine and print its resource
name. Run separately from the probe so the (slow) build is isolated.

    python spike/ae_deploy_spike.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vertexai
from vertexai import types as vtypes
from spike.spike_app import SpikeBidiApp

PROJECT = "REDACTED_PROJECT"
LOCATION = "us-central1"
BUCKET = "gs://REDACTED_PROJECT-ae-spike"

client = vertexai.Client(project=PROJECT, location=LOCATION)

print("Deploying spike bidi app to Agent Engine (EXPERIMENTAL)... this builds a container, ~several minutes.")
engine = client.agent_engines.create(
    agent=SpikeBidiApp(),
    config=vtypes.AgentEngineConfig(
        display_name="att-bidi-spike",
        staging_bucket=BUCKET,
        requirements=[
            "google-cloud-aiplatform[agent_engines]",
            "cloudpickle==3.1.2",
            "pydantic",
            "websockets",
        ],
        # AE has no py3.14 base image yet; pin 3.12. Ship the spike package as
        # source (relative path, resolved from cwd=module root) so it lands as
        # an importable top-level `spike` package and cloudpickle's by-name
        # reference (spike.spike_app) resolves on the remote.
        extra_packages=["spike"],
        python_version="3.12",
        agent_server_mode=vtypes.AgentServerMode.EXPERIMENTAL,
    ),
)
name = engine.api_resource.name
print("DEPLOYED:", name)
Path(ROOT / "spike" / ".engine_name").write_text(name)
print("Wrote spike/.engine_name")
