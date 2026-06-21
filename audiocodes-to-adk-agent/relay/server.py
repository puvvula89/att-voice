from dotenv import load_dotenv
load_dotenv()

import os
import uuid

from fastapi import FastAPI, WebSocket
from google.adk.sessions import InMemorySessionService

from relay.gateways.harness import HarnessGateway
from relay.agents_runtime.factory import make_factory
from relay.session_record import SessionRecord
from relay.steering import run_call

app = FastAPI()

# One shared session service for the whole process → all ADK agents (greeter +
# specialists) share a session by session_id, so context carries.
_session_service = InMemorySessionService()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    gateway = HarnessGateway(websocket)
    record = SessionRecord(session_id=str(uuid.uuid4()), caller="harness")
    factory = make_factory(
        session_service=_session_service,
        ces_app=os.environ["CES_APP"],
        ces_location=os.environ.get("CES_LOCATION", "us"),
        ae_engine=os.environ.get("AE_ENGINE_ID", ""),
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        ae_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        voice=os.environ.get("LIVE_VOICE", "Charon"),
    )
    await run_call(gateway, factory, record)
