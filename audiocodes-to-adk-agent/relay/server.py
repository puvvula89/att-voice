from dotenv import load_dotenv
load_dotenv()

import os
import pathlib
import uuid

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from google.adk.sessions import InMemorySessionService

from relay.caller_channels import BrowserGateway
from relay.agent_channels import make_factory
from relay.call_session import SessionRecord
from relay.call_steering import run_call

app = FastAPI()

# One shared session service for the whole process → all ADK agents (greeter +
# specialists) share a session by session_id, so context carries.
_session_service = InMemorySessionService()

# The demo UI is shipped in the image (harness/client.html) and served from the
# relay itself, so the deployed service is a single public URL: the page loads
# and opens a same-origin WebSocket to /ws — no separate static host needed.
_UI = pathlib.Path(__file__).resolve().parent.parent / "harness" / "client.html"


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
@app.get("/client.html")
async def index():
    return FileResponse(_UI, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    gateway = BrowserGateway(websocket)
    record = SessionRecord(session_id=str(uuid.uuid4()), caller="harness")
    factory = make_factory(
        session_service=_session_service,
        ces_app=os.environ.get("CES_APP", ""),
        ces_location=os.environ.get("CES_LOCATION", "us"),
        ae_engine=os.environ.get("AE_ENGINE_ID", ""),
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        ae_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        voice=os.environ.get("LIVE_VOICE", "Charon"),
    )
    await run_call(gateway, factory, record)
