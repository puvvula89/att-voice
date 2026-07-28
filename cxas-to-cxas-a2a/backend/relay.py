"""Browser <-> CXAS relay for the unified voice+chat client.

The browser cannot reach CXAS directly: the text path is unary gRPC (browsers
can't speak it) and the audio path needs a Google OAuth bearer token, which must
never ship to a page. So this relay sits in between, exactly like the ADK bundle's
`backend/server.py` does for Agent Engine.

Key design point — ONE session, BOTH modalities. CXAS's bidirectional session
protocol carries text *and* audio on the same socket:

    client -> server   BidiSessionClientMessage
                         .config          SessionConfig(session, audio configs)   (once, first)
                         .realtime_input  SessionInput(text=...)   <- typed turn
                         .realtime_input  SessionInput(audio=...)  <- mic frames

    server -> client   BidiSessionServerMessage
                         .session_output      SessionOutput(text, audio, turn_completed, end_session)
                         .recognition_result  ASR of what the user said
                         .interruption_signal  barge-in

So a single CXAS bidi websocket per browser connection gives us the unified
behaviour: the user can talk, then type, and it stays one conversation because the
`session` in the config never changes.

Requires the app to be on a LIVE model (live models accept both audio and text;
a text-only model cannot do audio).

Env: GOOGLE_CLOUD_PROJECT / CXAS_PROJECT, CXAS_LOCATION, VOICE_APP_ID.
"""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import google.auth
import google.auth.transport.requests
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("cxas.relay")

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# Matches cxas_scrapi.core.sessions.BIDI_SESSION_URI.
BIDI_URI = (
    "wss://ces.googleapis.com/ws/"
    "google.cloud.ces.v1.SessionService/BidiRunSession/locations/" + LOCATION
)

# Audio formats. Input is what the browser's audio.js produces (16 kHz LINEAR16);
# output is what we ask CXAS to synthesize back.
IN_SAMPLE_RATE = int(os.environ.get("IN_SAMPLE_RATE", "16000"))
OUT_SAMPLE_RATE = int(os.environ.get("OUT_SAMPLE_RATE", "24000"))

# Opener the relay sends to make the agent greet (see the `start` branch below).
GREETING_KICK = os.environ.get("GREETING_KICK", "hello")

app = FastAPI()

_creds = None


def _bearer_token() -> str:
    """Mint/refresh an ADC access token for the CXAS websocket."""
    global _creds
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def _config_message(session_id: str) -> str:
    """First frame on the CXAS socket — pins the session and the audio formats.

    `session` is the whole reason both modalities share state: it stays constant
    for the life of the connection, so typed and spoken turns land in one session.
    """
    return json.dumps({
        "config": {
            "session": f"{APP}/sessions/{session_id}",
            "inputAudioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": IN_SAMPLE_RATE,
            },
            "outputAudioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": OUT_SAMPLE_RATE,
            },
            "enableTextStreaming": True,
        }
    })


def _b64(raw) -> str:
    """Proto JSON returns bytes fields as base64 strings; normalise to str."""
    if isinstance(raw, str):
        return raw
    return base64.b64encode(raw).decode()


async def _browser_to_cxas(browser: WebSocket, cxas, state: dict):
    """Pump browser frames into the CXAS session.

    Text and audio are the same kind of message here — only the SessionInput field
    differs — which is what makes the unified UI possible.
    """
    while True:
        raw = await browser.receive_text()
        msg = json.loads(raw)
        kind = msg.get("type")

        if kind == "user_message":
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            state["awaiting"] = True
            await cxas.send(json.dumps({"realtimeInput": {"text": text}}))

        elif kind == "audio":
            # Mic frames: base64 16-bit LE PCM @ IN_SAMPLE_RATE, straight through.
            data = msg.get("data")
            if data:
                await cxas.send(json.dumps({"realtimeInput": {"audio": data}}))

        elif kind == "start":
            # CXAS does not greet on connect — it stays silent until first input.
            # An empty text errors (1011) and `event` expects a non-string type,
            # so kick the session with a benign opener. The browser never echoes
            # this (it only echoes what the user typed), so the user just sees
            # the agent's greeting.
            await cxas.send(json.dumps({"realtimeInput": {"text": GREETING_KICK}}))


async def _cxas_to_browser(browser: WebSocket, cxas, state: dict):
    """Pump CXAS output back to the browser as UI-shaped events."""
    async for raw in cxas:
        msg = json.loads(raw)

        # What the user said (ASR) — so spoken turns appear in the transcript
        # alongside typed ones.
        rec = msg.get("recognitionResult") or msg.get("recognition_result")
        if rec:
            text = rec.get("text") or rec.get("transcript") or ""
            if text:
                await browser.send_text(json.dumps(
                    {"type": "transcript", "role": "user", "text": text}))

        # Barge-in: the user started talking over the agent.
        if msg.get("interruptionSignal") or msg.get("interruption_signal"):
            await browser.send_text(json.dumps({"type": "interrupted"}))

        out = msg.get("sessionOutput") or msg.get("session_output")
        if out:
            # Agent text arrives STREAMED in fragments across many messages
            # ("Hmm, I see. Are any lights blinking on" … " your modem or router?"),
            # so send deltas and let the client accumulate them into one bubble
            # that is closed on turn_complete. Emitting one bubble per fragment
            # would shred a single reply into pieces.
            if out.get("text"):
                await browser.send_text(json.dumps(
                    {"type": "agent_delta", "text": out["text"]}))

            if out.get("audio"):
                await browser.send_text(json.dumps(
                    {"type": "audio", "data": _b64(out["audio"])}))

            if out.get("turnCompleted") or out.get("turn_completed"):
                state["awaiting"] = False
                await browser.send_text(json.dumps({"type": "turn_complete"}))

            if out.get("endSession") or out.get("end_session"):
                await browser.send_text(json.dumps({"type": "session_end"}))
                return

        if msg.get("endSession") or msg.get("end_session"):
            await browser.send_text(json.dumps({"type": "session_end"}))
            return

        # Server asking us to reconnect; treat as end of this leg.
        if msg.get("goAway") or msg.get("go_away"):
            return


def _explain(exc: BaseException) -> str:
    """Turn a relay/CXAS failure into something a user can act on.

    Quota is BY FAR the most common failure on this app, and its wire form is an
    opaque `1011 ... generic::resource_exhausted`. Saying so plainly — and that
    waiting fixes it — is the difference between "the demo is broken" and "try
    again in a minute".
    """
    text = str(exc)
    if "resource_exhausted" in text or "RESOURCE_EXHAUSTED" in text:
        return ("The agent is at capacity right now (quota exceeded). "
                "Wait a minute, then press Start again.")
    return "Connection to the agent failed."


async def _tell_browser(browser: WebSocket, text: str) -> None:
    """Best-effort error banner; never let reporting a failure raise its own."""
    try:
        await browser.send_text(json.dumps({"type": "error", "text": text}))
    except Exception:
        pass


@app.websocket("/session/{session_id}")
async def session_endpoint(browser: WebSocket, session_id: str):
    """One browser connection == one CXAS bidi session, carrying both modalities.

    `session_id` comes from the client and is the conversation anchor: reuse it to
    continue a conversation, mint a new one to start fresh.
    """
    await browser.accept()
    state = {"awaiting": False}
    _log.info("browser connected session=%s app=%s", session_id, APP_ID)

    headers = {"Authorization": f"Bearer {_bearer_token()}"}
    try:
        async with websockets.connect(
            BIDI_URI, additional_headers=headers, max_size=None, ping_interval=20
        ) as cxas:
            await cxas.send(_config_message(session_id))
            await browser.send_text(json.dumps(
                {"type": "session_info", "session_id": session_id}))

            up = asyncio.create_task(_browser_to_cxas(browser, cxas, state))
            down = asyncio.create_task(_cxas_to_browser(browser, cxas, state))
            done, pending = await asyncio.wait(
                {up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    _log.exception("pump failed", exc_info=exc)
                    # A pump dying is the COMMON failure (CXAS closes the socket
                    # with 1011 on quota), and it happens inside a task — so it
                    # never reaches the outer handler below. Without this the
                    # browser just goes silent and its controls grey out with no
                    # explanation, which reads as "the app is broken".
                    await _tell_browser(browser, _explain(exc))
    except WebSocketDisconnect:
        _log.info("browser disconnected session=%s", session_id)
    except Exception as exc:
        _log.exception("relay error session=%s", session_id)
        await _tell_browser(browser, _explain(exc))
    finally:
        try:
            await browser.close()
        except Exception:
            pass


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": APP}
