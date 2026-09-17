"""Translation bridge — AudioCodes Bot API WebSocket endpoint.

AGENT_MODE=dialout: an inbound call is the caller leg. The bridge
dials the agent through the dialout API, pairs the agent leg by the caller's
conversation ID, and crosses two Live Translate sessions between the legs.

AGENT_MODE=dialin: the agent calls the same number; the next inbound call after a
waiting caller becomes the agent leg (lab pairing by arrival order).

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
from bridge.dialout import DialoutClient
from bridge.echo import EchoTranslator
from bridge.metrics import CallMetrics
from bridge.pairing import CallRegistry
from bridge.translator import GeminiTranslator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bridge")

app = FastAPI()
registry = CallRegistry()
AGENT_JOIN_TIMEOUT_S = 60
DIALIN_WAIT_S = 180


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
            voice=os.environ.get("LIVE_VOICE", ""),
        )
    raise ValueError(f"Unknown TRANSLATOR={mode!r}")


# PRD §7.2: Session A (caller -> agent) is fixed to English with echo on, so English
# the caller speaks still reaches the agent. Session B targets the caller's language.
def _to_agent():
    return _translator("en", True)


def _to_caller():
    return _translator(os.environ["CALLER_LANGUAGE"], False)


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
            registry.fail_dialout(gateway.conversation_id)
            return
        mode = os.environ.get("AGENT_MODE", "loopback")
        caller_conv = (start.parameters.get("dialoutMetadata") or {}).get("callerConversationId")
        if mode == "dialin" and caller_conv is None:
            # Dial-in: the next inbound call after a waiting caller is the agent.
            caller_conv = registry.waiting_caller()
        if caller_conv:
            await _agent_leg(gateway, events, caller_conv)
        elif mode in ("dialout", "dialin"):
            await _caller_leg(gateway, events, dial=(mode == "dialout"))
        else:
            metrics = CallMetrics(gateway.conversation_id, "loopback")
            await run_direction(events, _to_agent(), gateway, metrics)
    finally:
        events.close()
        await gateway.end()


async def _caller_leg(gateway, events, dial: bool) -> None:
    conv = gateway.conversation_id
    pair = registry.create(conv)
    try:
        if dial:
            dialout = DialoutClient(
                api_url=os.environ.get("LIVEHUB_API_URL", "https://livehub.audiocodes.io"),
                client_id=os.environ["LIVEHUB_CLIENT_ID"],
                client_secret=os.environ["LIVEHUB_CLIENT_SECRET"],
            )
            pair.agent_conversation_id = await dialout.dial(
                bot=os.environ.get("LIVEHUB_BOT_NAME") or gateway.bot_name,
                target=os.environ["AGENT_NUMBER"],
                caller=os.environ["LIVEHUB_CALLER_ID"],
                metadata={"callerConversationId": conv},
            )
        else:
            log.info("caller waiting for agent to dial in conv=%s", conv)
        # Caller audio before the agent answers has nowhere to go; drop it.
        events.discard_audio = True
        joined = asyncio.create_task(pair.agent_joined.wait())
        failed = asyncio.create_task(pair.dialout_failed.wait())
        hung_up = asyncio.create_task(_next_end(events))
        timeout = AGENT_JOIN_TIMEOUT_S if dial else DIALIN_WAIT_S
        await asyncio.wait({joined, failed, hung_up}, timeout=timeout,
                           return_when=asyncio.FIRST_COMPLETED)
        joined.cancel()
        failed.cancel()
        if hung_up.done():
            return  # caller hung up before the agent answered
        hung_up.cancel()
        if not pair.agent_joined.is_set():
            log.warning("agent leg not connected conv=%s (dialout %s)", conv,
                        "failed" if pair.dialout_failed.is_set() else "timed out")
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
