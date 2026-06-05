"""Deploy the phone-upgrade CHAT (text) agent to Vertex AI Agent Engine.

Counterpart to deploy_agent_engine.py (voice/bidi). Deploys on a SEPARATE engine
but configures VertexAiSessionService at the SAME SESSION_ENGINE_ID as voice, so a
conversation started in one channel resumes in the other. Standard async_stream op
(no EXPERIMENTAL server mode).

    python deploy/deploy_chat_engine.py

Required env: GOOGLE_CLOUD_PROJECT, MCP_SERVER_URL, SESSION_ENGINE_ID (the shared
session-backing engine id — must match what voice uses).
Optional env: GOOGLE_CLOUD_LOCATION, AE_STAGING_BUCKET, CHAT_MODEL, CHAT_DISPLAY_NAME.
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
from backend.chat_app import chat_agent

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ.get("AE_STAGING_BUCKET") or f"{PROJECT}-agent-engine"
MCP_URL = os.environ["MCP_SERVER_URL"]
DISPLAY_NAME = os.environ.get("CHAT_DISPLAY_NAME", "att-phone-upgrade-chat")

# Cross-channel handoff REQUIRES a shared session store. Refuse to deploy chat
# without it — otherwise chat would silently use its own engine's sessions and
# never see voice's (and vice versa).
SESSION_ENGINE_ID = os.environ.get("SESSION_ENGINE_ID", "").strip()
if not SESSION_ENGINE_ID:
    sys.exit("SESSION_ENGINE_ID is required for the chat engine (the shared "
             "session-backing engine id; must match the voice agent).")

ENV_VARS = {
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "MCP_SERVER_URL": MCP_URL,
    "CHAT_MODEL": os.environ.get("CHAT_MODEL", "gemini-2.5-flash"),
    "SESSION_ENGINE_ID": SESSION_ENGINE_ID,
}

client = vertexai.Client(project=PROJECT, location=LOCATION)

print(f"Deploying CHAT agent to Agent Engine (project={PROJECT}, region={LOCATION}, "
      f"session_engine={SESSION_ENGINE_ID})... builds a container, ~several minutes.")
engine = client.agent_engines.create(
    agent=chat_agent,
    config=vtypes.AgentEngineConfig(
        display_name=DISPLAY_NAME,
        description="Phone-upgrade chat (text) agent; shares the voice session store.",
        staging_bucket=f"gs://{BUCKET}",
        requirements=[
            "google-cloud-aiplatform[agent_engines]",
            # See deploy_agent_engine.py: adk 2.2.0 broke Vertex Live resume; pin
            # 2.1.0 (constrains genai to <2). Keep chat on the same pinned stack so
            # the shared session store is read/written by identical library versions.
            "google-adk==2.1.0",
            "mcp",
        ],
        extra_packages=["backend"],          # relative → importable backend.* on remote
        python_version="3.12",               # AE has no py3.14 base image
        # No agent_server_mode=EXPERIMENTAL — async_stream is a standard op.
        # GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION are reserved (AE auto-provides them).
        env_vars=ENV_VARS,
    ),
)
name = engine.api_resource.name
print("DEPLOYED:", name)
(ROOT / "deploy" / ".chat_engine_name").write_text(name)
print("Wrote deploy/.chat_engine_name")
