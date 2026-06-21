from dotenv import load_dotenv
load_dotenv()

import json
import os
import pathlib
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.adk.sessions import InMemorySessionService

from relay.caller_channels import BrowserGateway
from relay.agent_channels import make_factory
from relay.call_session import SessionRecord
from relay.call_steering import run_call
from relay.call_bus import CallBus

app = FastAPI()

# One shared session service for the whole process → all ADK agents (greeter +
# specialists) share a session by session_id, so context carries.
_session_service = InMemorySessionService()

# Observe bridge: the caller call publishes its frames here; /observe monitors
# (the /audiocodes page) subscribe. Single active call (demo scope).
_bus = CallBus()

# The demo UI is shipped in the image (harness/client.html) and served from the
# relay itself, so the deployed service is a single public URL: the page loads
# and opens a same-origin WebSocket to /ws — no separate static host needed.
_UI = pathlib.Path(__file__).resolve().parent.parent / "harness" / "client.html"


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# The page is the same file in both modes; it picks caller vs observe from its
# own URL path (/browser = caller, /audiocodes = observe-only monitor).
@app.get("/")
@app.get("/client.html")
@app.get("/browser")
@app.get("/audiocodes")
async def index():
    return FileResponse(_UI, media_type="text/html", headers={"Cache-Control": "no-store"})


def _factory():
    return make_factory(
        session_service=_session_service,
        ces_app=os.environ.get("CES_APP", ""),
        ces_location=os.environ.get("CES_LOCATION", "us"),
        ae_engine=os.environ.get("AE_ENGINE_ID", ""),
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        ae_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        voice=os.environ.get("LIVE_VOICE", "Charon"),
    )


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """Caller channel (the /browser page). Drives one call; publishes to the bus."""
    await websocket.accept()
    gateway = BrowserGateway(websocket, bus=_bus)
    record = SessionRecord(session_id=str(uuid.uuid4()), caller="harness")
    _bus.start()
    try:
        await run_call(gateway, _factory(), record)
    finally:
        _bus.end()


@app.websocket("/observe")
async def observe(websocket: WebSocket):
    """Read-only monitor channel (the /audiocodes page). Receives call frames."""
    await websocket.accept()
    q = _bus.subscribe()
    try:
        while True:
            frame = await q.get()
            await websocket.send_text(json.dumps(frame))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _bus.unsubscribe(q)
