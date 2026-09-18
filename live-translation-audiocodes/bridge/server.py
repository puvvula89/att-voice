"""Translation bridge — AudioCodes Bot API WebSocket endpoint.

AGENT_MODE=dialin: two inbound calls. The first is the caller leg; the agent calls
the same number and the next inbound call after a waiting caller becomes the agent
leg (lab pairing by arrival order). Two Live Translate sessions are crossed between
the legs, one per direction.

AGENT_MODE=loopback: one leg hears its own translation, for
single-phone testing.
"""
from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging
import os

from fastapi import FastAPI, WebSocket

from bridge.audiocodes_gateway import AudioCodesGateway
from bridge.call import EventPump, run_direction, run_pair, wait_for_start
from bridge.channels import InboundEnd
from bridge.echo import EchoTranslator
from bridge.metrics import CallMetrics
from bridge.pairing import CallRegistry
from bridge import settings
from bridge.translator import GeminiTranslator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bridge")

app = FastAPI()
registry = CallRegistry()
DIALIN_WAIT_S = 180

# Serve the console from this process when SERVE_CONSOLE is set, so a deployed
# bridge can be watched live. It reads the event files this process writes, which is
# only possible from inside the same container. Off by default: run it as its own
# process locally, where nothing it does can touch the audio loop.
if os.environ.get("SERVE_CONSOLE", "").lower() in ("1", "true", "yes"):
    from console.app import app as console_app

    app.mount("/console", console_app)
    log.info("console mounted at /console")


def _translator(target_language: str, echo_target_language: bool):
    mode = os.environ.get("TRANSLATOR", "echo")
    if mode == "echo":
        return EchoTranslator()
    if mode == "gemini":
        return GeminiTranslator(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            model=os.environ["LIVE_TRANSLATE_MODEL"],
            target_language=target_language,
            echo_target_language=echo_target_language,
        )
    raise ValueError(f"Unknown TRANSLATOR={mode!r}")


# PRD §7.2: Session A (caller -> agent) is fixed to English; Session B targets the
# caller's language.
#
# Echo makes the model reproduce speech that is already in the target language, so
# English the caller speaks still reaches the agent. It also makes the model rebroadcast
# any English it picks up -- the agent's own voice bleeding into the caller's handset,
# for instance -- which adds output this direction does not need and which the session
# then queues behind. Google's guidance is to leave it off for interpreter setups.
def _to_agent():
    echo = os.environ.get("ECHO_TO_AGENT", "false").lower() in ("1", "true", "yes")
    return _translator("en", echo)


def _to_caller():
    # Read per call, so the language picked in the console applies from the next call.
    return _translator(settings.caller_language(), False)


def _authorized(websocket: WebSocket) -> bool:
    """Compare the VAIC `Authorization: Bearer` header with AUDIOCODES_TOKEN.
    Open when the variable is unset (local development only)."""
    expected = os.environ.get("AUDIOCODES_TOKEN", "")
    if not expected:
        return True
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and token == expected


@app.get("/audiocodes-ws")
@app.post("/audiocodes-ws")
async def connectivity_check():
    # Live Hub validates the bot URL over HTTP and checks this exact body.
    return {"type": "ac-bot-api", "success": True}


@app.websocket("/audiocodes-ws")
async def audiocodes_ws(websocket: WebSocket):
    if not _authorized(websocket):
        log.warning("rejected unauthorized connection")
        await websocket.close(code=1008)
        return
    await websocket.accept()
    gateway = AudioCodesGateway(websocket)
    if not await gateway.handshake():
        return  # validation-only connection
    events = EventPump(gateway)
    try:
        start = await wait_for_start(gateway, events, _greeting())
        if start is None:
            return
        mode = os.environ.get("AGENT_MODE", "loopback")
        # The next inbound call after a waiting caller is the agent leg.
        caller_conv = registry.waiting_caller() if mode == "dialin" else None
        if caller_conv:
            await _agent_leg(gateway, events, caller_conv)
        elif mode == "dialin":
            await _caller_leg(gateway, events)
        else:
            metrics = CallMetrics(gateway.conversation_id, "loopback")
            await run_direction(events, _to_agent(), gateway, metrics)
    finally:
        events.close()
        await gateway.end()


async def _caller_leg(gateway, events) -> None:
    conv = gateway.conversation_id
    pair = registry.create(conv)
    try:
        log.info("caller waiting for agent to dial in conv=%s", conv)
        # Caller audio before the agent answers has nowhere to go; drop it.
        events.discard_audio = True
        joined = asyncio.create_task(pair.agent_joined.wait())
        hung_up = asyncio.create_task(_next_end(events))
        await asyncio.wait({joined, hung_up}, timeout=DIALIN_WAIT_S,
                           return_when=asyncio.FIRST_COMPLETED)
        joined.cancel()
        if hung_up.done():
            return  # caller hung up before the agent answered
        hung_up.cancel()
        if not pair.agent_joined.is_set():
            log.warning("agent leg not connected conv=%s (timed out)", conv)
            return
        events.discard_audio = False
        log.info("paired caller=%s agent=%s", conv, pair.agent_gateway.conversation_id)
        await run_pair(
            events, gateway, pair.agent_events, pair.agent_gateway,
            _to_agent(), _to_caller(),
            CallMetrics(conv, "caller-to-agent"), CallMetrics(conv, "agent-to-caller"),
        )
    except Exception:
        log.exception("caller leg failed conv=%s", conv)
    finally:
        pair.finished.set()
        registry.remove(conv)
        if pair.agent_gateway is not None:
            await pair.agent_gateway.end()


async def _next_end(events) -> None:
    """Return when the leg ends. Only non-audio events arrive while audio is discarded."""
    while not isinstance(await events.__anext__(), InboundEnd):
        pass


async def _agent_leg(gateway, events, caller_conv: str) -> None:
    pair = registry.join(caller_conv, gateway, events)
    if pair is None:
        log.warning("no waiting caller for agent leg conv=%s", caller_conv)
        return
    # The caller leg drives both directions; this handler only keeps the socket open.
    await pair.finished.wait()


def _greeting(ms: int = 200, rate: int = 24000) -> bytes | None:
    """ANSWER_PROMPT: silence (default) | tone | none."""
    mode = os.environ.get("ANSWER_PROMPT", "silence").lower()
    n = rate * ms // 1000
    if mode == "silence":
        return bytes(n * 2)
    if mode == "tone":
        import array
        import math
        return array.array(
            "h", (int(6000 * math.sin(2 * math.pi * 660 * i / rate)) for i in range(n))
        ).tobytes()
    return None
