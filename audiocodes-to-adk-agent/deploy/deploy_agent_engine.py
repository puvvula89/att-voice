from dotenv import load_dotenv
load_dotenv()

import os

import vertexai
from vertexai import types as vtypes

from relay.agent_app import SteeringApp

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ["STAGING_BUCKET"]
DISPLAY_NAME = "att-steering-adk"

ENV_VARS = {
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "LIVE_MODEL": os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio"),
    "LIVE_VOICE": os.environ.get("LIVE_VOICE", "Charon"),
}

cfg = vtypes.AgentEngineConfig(
    display_name=DISPLAY_NAME,
    description="ADK multi-agent steering app (greeter + specialists), Live/bidi.",
    staging_bucket=f"gs://{BUCKET}",
    requirements=[
        "google-cloud-aiplatform[agent_engines]",
        "google-adk==2.1.0",
        "cloudpickle==3.1.2",
        "websockets",
    ],
    extra_packages=["relay", "agents"],   # RELATIVE → importable on remote
    python_version="3.12",
    agent_server_mode=vtypes.AgentServerMode.EXPERIMENTAL,
    env_vars=ENV_VARS,
)

client = vertexai.Client(project=PROJECT, location=LOCATION)
existing = next(
    (e for e in client.agent_engines.list()
     if getattr(e.api_resource, "display_name", "") == DISPLAY_NAME),
    None,
)
app = SteeringApp()
if existing is not None:
    name = existing.api_resource.name
    print(f"Updating {name.split('/')[-1]} in place... (~several minutes)")
    engine = client.agent_engines.update(name=name, agent=app, config=cfg)
else:
    print("Creating Agent Engine... (~several minutes)")
    engine = client.agent_engines.create(agent=app, config=cfg)

print("AE_ENGINE_ID:", engine.api_resource.name)
