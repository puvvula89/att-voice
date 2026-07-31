"""Browser <-> CXAS relay for the unified voice+chat client.

WHY THIS EXISTS AT ALL
    A browser cannot open the CXAS audio stream itself. Authentication is read from
    the `Authorization` header, and the browser WebSocket API — `new WebSocket(url,
    protocols)` — has no way to set headers. Query parameters, the
    `Sec-WebSocket-Protocol` field and a token in the first frame were all tested
    against the live service and all rejected. Google's own web widget takes the
    same route: its `api-uri` is documented as "a websocket url to be used as
    websocket proxy for audio sessions".

    So the relay is not a workaround, it is the supported browser topology. A NATIVE
    app needs none of this: it can set headers and speak gRPC directly to CXAS.

TWO LEGS, TWO TRANSPORTS
    browser <-- WebSocket, JSON --> relay <-- gRPC bidi streaming --> CXAS

    The browser leg stays JSON so the page stays debuggable in devtools. The CXAS
    leg is gRPC: audio rides as raw proto `bytes` instead of base64 inside JSON,
    which removes a 33% tax and a JSON parse per 100 ms of audio.

ONE SESSION, BOTH MODALITIES
    CXAS's bidirectional protocol carries text *and* audio on the same stream:

    client -> server   BidiSessionClientMessage
                         .config          SessionConfig(session, audio configs)  (once, first)
                         .realtime_input  SessionInput(text=...)   <- typed turn
                         .realtime_input  SessionInput(audio=...)  <- mic frames

    server -> client   BidiSessionServerMessage   (a oneof)
                         .session_output      SessionOutput(text | audio | end_session,
                                                            turn_completed)
                         .recognition_result  ASR of what the user said
                         .interruption_signal  barge-in

    Modality is a per-TURN field, not a per-connection choice, so the user can talk,
    then type, and it stays one conversation: the `session` in the config never
    changes. Splitting text and audio across two transports would split the session.

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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.api_core import exceptions
from google.api_core.client_options import ClientOptions
from google.cloud import ces_v1beta as ces

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("cxas.relay")

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "ivr-and-app-voice")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# CES is a global endpoint; the region lives in the resource name, not the host.
CES_ENDPOINT = os.environ.get("CES_ENDPOINT", "ces.googleapis.com")

# Audio formats. Input is what the browser's audio.js produces (16 kHz LINEAR16);
# output is what we ask CXAS to synthesize back.
IN_SAMPLE_RATE = int(os.environ.get("IN_SAMPLE_RATE", "16000"))
OUT_SAMPLE_RATE = int(os.environ.get("OUT_SAMPLE_RATE", "24000"))

# Opener the relay sends to make the agent greet (see the `start` branch below).
GREETING_KICK = os.environ.get("GREETING_KICK", "hello")

app = FastAPI()

_client: ces.SessionServiceAsyncClient | None = None


def _session_client() -> ces.SessionServiceAsyncClient:
    """One shared async gRPC client; it multiplexes every call over one HTTP/2 channel.

    Credentials come from ADC and the client refreshes them itself — the reason the
    old hand-rolled bearer-token helper is gone.
    """
    global _client
    if _client is None:
        _client = ces.SessionServiceAsyncClient(
            client_options=ClientOptions(api_endpoint=CES_ENDPOINT)
        )
    return _client


def _config_message(session_id: str) -> ces.BidiSessionClientMessage:
    """First message on the CXAS stream — pins the session and the audio formats.

    `session` is the whole reason both modalities share state: it stays constant
    for the life of the stream, so typed and spoken turns land in one session.
    """
    return ces.BidiSessionClientMessage(
        config=ces.SessionConfig(
            session=f"{APP}/sessions/{session_id}",
            input_audio_config=ces.InputAudioConfig(
                audio_encoding=ces.AudioEncoding.LINEAR16,
                sample_rate_hertz=IN_SAMPLE_RATE,
            ),
            output_audio_config=ces.OutputAudioConfig(
                audio_encoding=ces.AudioEncoding.LINEAR16,
                sample_rate_hertz=OUT_SAMPLE_RATE,
            ),
            enable_text_streaming=True,
        )
    )


async def _browser_to_cxas(browser: WebSocket, outbound: asyncio.Queue, state: dict):
    """Pump browser frames onto the outbound queue feeding the CXAS stream.

    Text and audio are the same kind of message here — only the SessionInput field
    differs — which is what makes the unified UI possible. The browser protocol is
    unchanged by the move to gRPC: still JSON, still `user_message` / `audio` / `start`.
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
            await outbound.put(ces.BidiSessionClientMessage(
                realtime_input=ces.SessionInput(text=text)))

        elif kind == "audio":
            # Mic frames arrive base64-encoded from the browser; the proto field is
            # `bytes`, so decode here. This is where the 33% base64 tax is paid on
            # the browser leg and dropped on the CXAS leg.
            data = msg.get("data")
            if data:
                await outbound.put(ces.BidiSessionClientMessage(
                    realtime_input=ces.SessionInput(audio=base64.b64decode(data))))

        elif kind == "start":
            # CXAS does not greet on connect — it stays silent until first input.
            # An empty text is rejected and `event` expects a non-string type, so
            # kick the session with a benign opener. The browser never echoes this
            # (it only echoes what the user typed), so the user just sees the
            # agent's greeting.
            await outbound.put(ces.BidiSessionClientMessage(
                realtime_input=ces.SessionInput(text=GREETING_KICK)))


async def _cxas_to_browser(browser: WebSocket, responses, state: dict):
    """Pump CXAS output back to the browser as UI-shaped events.

    Server messages are a oneof (`message_type`), so exactly one branch applies per
    message — no need to test every field the way the proto-JSON version did.
    """
    async for msg in responses:
        kind = ces.BidiSessionServerMessage.pb(msg).WhichOneof("message_type")

        # What the user said (ASR) — so spoken turns appear in the transcript
        # alongside typed ones.
        if kind == "recognition_result":
            text = msg.recognition_result.transcript
            if text:
                await browser.send_text(json.dumps(
                    {"type": "transcript", "role": "user", "text": text}))

        # Barge-in: the user started talking over the agent.
        elif kind == "interruption_signal":
            await browser.send_text(json.dumps({"type": "interrupted"}))

        elif kind == "session_output":
            out = msg.session_output
            output = ces.SessionOutput.pb(out).WhichOneof("output_type")

            # Agent text arrives STREAMED in fragments across many messages
            # ("Hmm, I see. Are any lights blinking on" … " your modem or router?"),
            # so send deltas and let the client accumulate them into one bubble
            # that is closed on turn_complete. Emitting one bubble per fragment
            # would shred a single reply into pieces.
            if output == "text" and out.text:
                await browser.send_text(json.dumps(
                    {"type": "agent_delta", "text": out.text}))

            elif output == "audio" and out.audio:
                await browser.send_text(json.dumps(
                    {"type": "audio", "data": base64.b64encode(out.audio).decode()}))

            # turn_completed is NOT part of the output oneof, so it can ride along
            # with any of the branches above and must be checked separately.
            if out.turn_completed:
                state["awaiting"] = False
                await browser.send_text(json.dumps({"type": "turn_complete"}))

            if output == "end_session":
                await browser.send_text(json.dumps({"type": "session_end"}))
                return

        elif kind == "end_session":
            await browser.send_text(json.dumps({"type": "session_end"}))
            return

        # Server asking us to reconnect; treat as end of this leg.
        elif kind == "go_away":
            return


def _explain(exc: BaseException) -> str:
    """Turn a relay/CXAS failure into something a user can act on.

    Quota is BY FAR the most common failure on this app. Over gRPC it arrives as a
    typed ResourceExhausted rather than the websocket path's opaque
    `1011 ... generic::resource_exhausted`, so match the type first and keep the
    string check as a fallback for anything that reaches us wrapped. Saying plainly
    that waiting fixes it is the difference between "the demo is broken" and "try
    again in a minute".
    """
    if isinstance(exc, exceptions.ResourceExhausted):
        return ("The agent is at capacity right now (quota exceeded). "
                "Wait a minute, then press Start again.")
    if isinstance(exc, exceptions.PermissionDenied):
        return ("The relay is not authorised to open a session. Its service "
                "account needs roles/ces.client.")
    text = str(exc)
    if "resource_exhausted" in text.lower():
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

    # gRPC takes the request side as an async iterator rather than a socket you
    # call send() on, so the browser pump writes here and the iterator drains it.
    outbound: asyncio.Queue = asyncio.Queue()

    async def requests():
        """Config first, then whatever the browser produces, until it disconnects."""
        yield _config_message(session_id)
        while True:
            message = await outbound.get()
            if message is None:  # sentinel: close the request half cleanly
                return
            yield message

    try:
        # Routing metadata must be supplied by hand. For a unary call GAPIC derives
        # `x-goog-request-params` from a path-templated request field, but here the
        # `session` lives inside the first STREAMED message, which the client cannot
        # see when it opens the channel. Without this the global endpoint answers
        # HTTP 404 and grpc surfaces it as UNIMPLEMENTED.
        metadata = [("x-goog-request-params", f"session={APP}/sessions/{session_id}")]
        responses = await _session_client().bidi_run_session(
            requests=requests(), metadata=metadata)
        await browser.send_text(json.dumps(
            {"type": "session_info", "session_id": session_id}))

        up = asyncio.create_task(_browser_to_cxas(browser, outbound, state))
        down = asyncio.create_task(_cxas_to_browser(browser, responses, state))
        try:
            done, pending = await asyncio.wait(
                {up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    _log.exception("pump failed", exc_info=exc)
                    # A pump dying is the COMMON failure (CXAS aborts the stream
                    # on quota), and it happens inside a task — so it never
                    # reaches the outer handler below. Without this the browser
                    # just goes silent and its controls grey out with no
                    # explanation, which reads as "the app is broken".
                    await _tell_browser(browser, _explain(exc))
        finally:
            # Let the request generator finish so gRPC can half-close instead of
            # being cancelled mid-stream.
            await outbound.put(None)
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
