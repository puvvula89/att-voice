"""Deploy the phone-upgrade Live agent to Vertex AI Agent Engine (Topology B).

Packages the whole `backend/` package (agent, callbacks, formatter, templates,
the bidi wrapper) as source, points the agent at the Cloud Run MCP server via
MCP_SERVER_URL, and deploys in EXPERIMENTAL server mode (required for bidi).

    python deploy/deploy_agent_engine.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vertexai
from vertexai import types as vtypes
from backend.agent_app import live_agent

PROJECT = "REDACTED_PROJECT"
LOCATION = "us-central1"
BUCKET = "gs://REDACTED_PROJECT-agent-engine"
MCP_URL = "https://att-mcp-phone-upgrade-REDACTED_PROJECT_NUMBER.us-central1.run.app/mcp"

client = vertexai.Client(project=PROJECT, location=LOCATION)

print("Deploying phone-upgrade Live agent to Agent Engine (EXPERIMENTAL)... builds a container, ~several minutes.")
engine = client.agent_engines.create(
    agent=live_agent,
    config=vtypes.AgentEngineConfig(
        display_name="att-phone-upgrade-live",
        description="Phone-upgrade voice agent (Live/bidi) consuming the Cloud Run MCP data tools.",
        staging_bucket=BUCKET,
        requirements=[
            "google-cloud-aiplatform[agent_engines]",
            "google-adk>=2.0,<3",
            "mcp",
            "cloudpickle==3.1.2",
            "websockets",
        ],
        extra_packages=["backend"],          # relative → importable backend.* on remote
        python_version="3.12",               # AE has no py3.14 base image
        agent_server_mode=vtypes.AgentServerMode.EXPERIMENTAL,
        # GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION are reserved (AE auto-provides them).
        env_vars={
            "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
            "MCP_SERVER_URL": MCP_URL,
            "LIVE_MODEL": "gemini-live-2.5-flash-native-audio",
            "LIVE_VOICE": "Charon",
        },
    ),
)
name = engine.api_resource.name
print("DEPLOYED:", name)
Path(ROOT / "deploy" / ".engine_name").write_text(name)
print("Wrote deploy/.engine_name")
