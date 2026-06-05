"""Deploy the phone-upgrade Live agent to Vertex AI Agent Engine (Topology B).

All config comes from the environment (.env), so this deploys to any project.
Packages the whole `backend/` package as source, points the agent at the MCP
server via MCP_SERVER_URL, and deploys in EXPERIMENTAL server mode (bidi).

    python deploy/deploy_agent_engine.py

Required env: GOOGLE_CLOUD_PROJECT, MCP_SERVER_URL.
Optional env: GOOGLE_CLOUD_LOCATION (us-central1), AE_STAGING_BUCKET
(<project>-agent-engine), AGENT_DISPLAY_NAME, LIVE_MODEL, LIVE_VOICE.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import vertexai
from vertexai import types as vtypes
from backend.agent_app import live_agent

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ.get("AE_STAGING_BUCKET") or f"{PROJECT}-agent-engine"
MCP_URL = os.environ["MCP_SERVER_URL"]
DISPLAY_NAME = os.environ.get("AGENT_DISPLAY_NAME", "att-phone-upgrade-live")

# Shared session store across channels. Unset → the agent uses its own engine id
# (Agent Engine auto-injects it as GOOGLE_CLOUD_AGENT_ENGINE_ID).
SESSION_ENGINE_ID = os.environ.get("SESSION_ENGINE_ID", "").strip()

ENV_VARS = {
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "MCP_SERVER_URL": MCP_URL,
    "LIVE_MODEL": os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio"),
    "LIVE_VOICE": os.environ.get("LIVE_VOICE", "Charon"),
}
if SESSION_ENGINE_ID:
    ENV_VARS["SESSION_ENGINE_ID"] = SESSION_ENGINE_ID

client = vertexai.Client(project=PROJECT, location=LOCATION)

print(f"Deploying agent to Agent Engine (project={PROJECT}, region={LOCATION})... builds a container, ~several minutes.")
engine = client.agent_engines.create(
    agent=live_agent,
    config=vtypes.AgentEngineConfig(
        display_name=DISPLAY_NAME,
        description="Phone-upgrade voice agent (Live/bidi) consuming the MCP data tools.",
        staging_bucket=f"gs://{BUCKET}",
        requirements=[
            "google-cloud-aiplatform[agent_engines]",
            # PINNED: google-adk 2.2.0 (2026-06-04) regressed Vertex Live session
            # resume — it pulls google-genai 2.x, whose Live converter sets/forwards
            # live_connect_config.history_config, which the Vertex (Enterprise Agent
            # Platform) Live API rejects ("history_config ... only supported in ...
            # Developer API mode"). 2.1.0 is the last good release; it constrains
            # genai to <2,>=1.72 (the 1.x line that handles resume correctly). Do NOT
            # pin genai here — let adk 2.1.0 resolve it (genai==2.x conflicts).
            # Unpinned adk ranges cause silent drift between deploys — keep this pinned.
            "google-adk==2.1.0",
            "mcp",
            "cloudpickle==3.1.2",
            "websockets",
        ],
        extra_packages=["backend"],          # relative → importable backend.* on remote
        python_version="3.12",               # AE has no py3.14 base image
        agent_server_mode=vtypes.AgentServerMode.EXPERIMENTAL,
        # GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION are reserved (AE auto-provides them).
        env_vars=ENV_VARS,
    ),
)
name = engine.api_resource.name
print("DEPLOYED:", name)
(ROOT / "deploy" / ".engine_name").write_text(name)
print("Wrote deploy/.engine_name")
