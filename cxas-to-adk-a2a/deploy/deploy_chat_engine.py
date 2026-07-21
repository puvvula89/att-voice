"""Deploy the phone-upgrade CHAT (text) agent to Vertex AI Agent Engine as a
NATIVE A2A endpoint.

A2A variant of the chat deploy: instead of the custom ``async_stream`` app, this
deploys the ``A2aAgent`` template (``backend/a2a_app.py``), so Agent Engine serves
an A2A surface at ``…/reasoningEngines/{id}/a2a`` (card at ``/v1/card``,
``/v1/message:send``). CES calls it directly over A2A (RemoteAgentTool, P4SA auth)
— no HTTP adapter. Still configures VertexAiSessionService at the SAME
SESSION_ENGINE_ID as voice, so a conversation started in one channel resumes in
the other.

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
# The deployed object is the A2aAgent template instance; agent_framework="a2a" is
# auto-detected by agent_engines.create, which serves the a2a_extension operations.
from backend.a2a_app import a2a_agent

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ.get("AE_STAGING_BUCKET") or f"{PROJECT}-agent-engine"
MCP_URL = os.environ["MCP_SERVER_URL"]
# Distinct default name so the A2A variant deploys a SEPARATE engine and never
# overwrites the live cxas-to-adk chat engine.
DISPLAY_NAME = os.environ.get("CHAT_DISPLAY_NAME", "att-phone-upgrade-chat-a2a")

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

cfg = vtypes.AgentEngineConfig(
        display_name=DISPLAY_NAME,
        description="Phone-upgrade chat (text) agent; shares the voice session store.",
        staging_bucket=f"gs://{BUCKET}",
        # Keep one instance warm so the first IVR/chat turn doesn't pay a cold start
        # (~8-10s of the ~15s first-turn latency was engine cold start). max_instances
        # bounds the always-on cost. Override via CHAT_MIN_INSTANCES / CHAT_MAX_INSTANCES.
        min_instances=int(os.environ.get("CHAT_MIN_INSTANCES", "1")),
        max_instances=int(os.environ.get("CHAT_MAX_INSTANCES", "3")),
        requirements=[
            "google-cloud-aiplatform[agent_engines]",
            # See deploy_agent_engine.py: adk 2.2.0 broke Vertex Live resume; pin
            # 2.1.0 (constrains genai to <2). Keep chat on the same pinned stack so
            # the shared session store is read/written by identical library versions.
            "google-adk==2.1.0",
            "mcp",
            # A2A server runtime used by the A2aAgent template + our executor
            # (a2a.server.*, a2a.helpers.proto_helpers). 1.x is the proto-based line
            # the installed aiplatform a2a template targets (PROTOCOL_VERSION 1.0).
            "a2a-sdk>=1.1,<2",
        ],
        extra_packages=["backend"],          # relative → importable backend.* on remote
        python_version="3.12",               # AE has no py3.14 base image
        # agent_framework="a2a" is auto-detected from the A2aAgent; the SDK serves the
        # a2a_extension operations (message:send, card, tasks) — no agent_server_mode.
        # GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION are reserved (AE auto-provides them).
        env_vars=ENV_VARS,
)

# Idempotent deploy: UPDATE in place if a chat engine with this display name exists,
# else create. Keeps the chat engine id stable across deploys (see
# deploy_agent_engine.py); only the first run creates.
existing = next(
    (e for e in client.agent_engines.list()
     if getattr(e.api_resource, "display_name", "") == DISPLAY_NAME),
    None,
)
if existing is not None:
    name = existing.api_resource.name
    print(f"Updating existing CHAT Agent Engine {name.split('/')[-1]} in place "
          f"(session_engine={SESSION_ENGINE_ID})... rebuilds the container, ~several minutes.")
    engine = client.agent_engines.update(name=name, agent=a2a_agent, config=cfg)
else:
    print(f"Creating CHAT Agent Engine (project={PROJECT}, region={LOCATION}, "
          f"session_engine={SESSION_ENGINE_ID})... builds a container, ~several minutes.")
    engine = client.agent_engines.create(agent=a2a_agent, config=cfg)

name = engine.api_resource.name
print("DEPLOYED:", name)
(ROOT / "deploy" / ".chat_engine_name").write_text(name)
print("Wrote deploy/.chat_engine_name")
