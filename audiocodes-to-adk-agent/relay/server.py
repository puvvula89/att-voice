from dotenv import load_dotenv
load_dotenv()

import json
import logging
import os
import pathlib
import uuid

_log = logging.getLogger("audiocodes")  # shared with relay.caller_channels
if not _log.handlers:                    # ensure INFO surfaces in Cloud Run regardless of uvicorn config
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from google.adk.sessions import InMemorySessionService

from relay.caller_channels import BrowserGateway, AudioCodesGateway
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


def _audiocodes_authorized(websocket: WebSocket) -> bool:
    """Check the VAIC Bearer token from the WS upgrade Authorization header.

    AudioCodes VoiceAI Connect sends `Authorization: Bearer <token>` (the provider
    `token` parameter). We compare it to AUDIOCODES_TOKEN. If the env var is unset,
    auth is open (local/dev) — set it in any shared/deployed environment.
    """
    expected = os.environ.get("AUDIOCODES_TOKEN", "")
    if not expected:
        return True
    header = websocket.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and token == expected


@app.get("/audiocodes-ws")
@app.post("/audiocodes-ws")
async def audiocodes_ws_probe():
    """AudioCodes Bot API 'Connectivity Check' for LiveHub's bot validation.

    LiveHub validates the bot URL with a plain HTTP GET (wss->https, Bearer token)
    BEFORE any call. Per the AudioCodes Bot API spec, the bot must reply 200 with
    EXACTLY this JSON body — the status code alone isn't enough; LiveHub checks the
    body, so a generic 200 still fails as 'bot connection data seems to be invalid'.
    The real call rides the WebSocket upgrade on this same path (routed separately
    by ASGI scope); this HTTP handler never creates a conversation.
    """
    return {"type": "ac-bot-api", "success": True}


@app.websocket("/audiocodes-ws")
async def audiocodes_ws(websocket: WebSocket):
    """AudioCodes VoiceAI Connect caller channel — a real phone call.

    Same steering loop and observe bridge as /ws; only the gateway differs. Point
    the VAIC bot provider's `botUrl` at wss://<host>/audiocodes-ws.
    """
    peer = websocket.client.host if websocket.client else "?"
    if not _audiocodes_authorized(websocket):
        _log.warning("[audiocodes] REJECTED unauthorized connection from %s", peer)
        await websocket.close(code=1008)  # policy violation -> 403 at handshake
        return
    # DIAGNOSTIC: dump the upgrade headers + offered subprotocols to see what the
    # peer (LiveHub validation) negotiates before any frame.
    hdrs = {k: v for k, v in websocket.headers.items()
            if k.lower() in ("user-agent", "sec-websocket-protocol", "sec-websocket-version",
                             "origin", "x-ac-conversation-id", "ac-conversation-id", "ac-caller-number")}
    _log.info("[audiocodes] connection accepted from %s subprotocols=%s headers=%s",
              peer, websocket.scope.get("subprotocols"), hdrs)
    await websocket.accept()
    gateway = AudioCodesGateway(websocket, bus=_bus)
    try:
        await gateway.handshake()  # session.initiate -> session.accepted (negotiate coders)
    except Exception as e:
        _log.warning("[audiocodes] handshake failed from %s: %r", peer, e)
        try:
            await websocket.close()
        except Exception:
            pass
        return
    record = SessionRecord(
        session_id=gateway.conversation_id or str(uuid.uuid4()),
        caller=gateway.caller or "audiocodes",
    )
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
