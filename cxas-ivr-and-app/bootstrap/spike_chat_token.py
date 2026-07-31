"""Spike: can a chat_token stream AUDIO to CXAS from a client with no service-account credential?

Two questions, answered in order. The second only matters if the first passes.

  Q1  Does GenerateChatToken's chat_token authorise BidiRunSession at all, or is it
      scoped to something narrower than the full session API?
  Q2  How is the token presented on the wire? A browser's WebSocket API cannot set
      request headers -- that limitation is the entire reason the relay exists. So a
      viable direct-connect design needs the token to ride in a query parameter, the
      Sec-WebSocket-Protocol subprotocol field, or a first-frame handshake.

Q1 is tested with an Authorization header, which a browser cannot send. That is
deliberate: it isolates "is the token valid for this RPC" from "can a browser present
it". If Q1 fails, direct-connect is dead for voice and no placement matters.

Run:  python spike_chat_token.py
Env:  CXAS_PROJECT / GOOGLE_CLOUD_PROJECT, CXAS_LOCATION, VOICE_APP_ID, SPIKE_DEPLOYMENT_ID
"""

import asyncio
import base64
import json
import os
import uuid

import websockets
from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud import ces_v1beta as ces

load_dotenv(os.environ.get("SPIKE_ENV", ".env"))

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
DEPLOYMENT_ID = os.environ.get("SPIKE_DEPLOYMENT_ID")

APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
# v1beta, NOT v1: the chat token's `aud` claim is
# https://ces.googleapis.com/google.cloud.ces.v1beta.SessionService, and the
# server rejects a v1 path with "Audience mismatch" before looking at anything else.
BIDI_URI = (
    "wss://ces.googleapis.com/ws/"
    "google.cloud.ces.v1beta.SessionService/BidiRunSession/locations/" + LOCATION
)

IN_RATE, OUT_RATE = 16000, 24000

# 200 ms of digital silence at 16 kHz LINEAR16. Enough to prove the server accepts an
# audio frame on this connection; not enough to trigger a model turn, which keeps the
# live-model quota cost of the spike near zero.
SILENCE = base64.b64encode(b"\x00\x00" * int(IN_RATE * 0.2)).decode()


def mint_token(session_id: str) -> str:
    """Ask CXAS for a session-scoped chat token. Runs with ADC, server-side."""
    client = ces.WidgetServiceClient(
        client_options=ClientOptions(api_endpoint="ces.googleapis.com")
    )
    resp = client.generate_chat_token(
        request=ces.GenerateChatTokenRequest(
            name=f"{APP}/sessions/{session_id}",
            deployment=f"{APP}/deployments/{DEPLOYMENT_ID}",
        )
    )
    print(f"  token minted, expires {resp.expire_time}")
    return resp.chat_token


def config_frame(session_id: str, token: str | None = None) -> str:
    """First frame: pins the session and the audio formats.

    When `token` is set we also smuggle it into the config, on the theory that a
    handshake-style presentation is how the widget does it. An unknown field is
    normally rejected by proto JSON parsing, which is itself a useful signal.
    """
    config = {
        "session": f"{APP}/sessions/{session_id}",
        "inputAudioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": IN_RATE},
        "outputAudioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": OUT_RATE},
        "enableTextStreaming": True,
    }
    if token:
        config["chatToken"] = token
    return json.dumps({"config": config})


async def attempt(label: str, token: str, session_id: str, *, headers=None, uri=None,
                  subprotocols=None, in_config=False) -> tuple[str, str]:
    """Open a socket with the token presented one particular way, then send audio.

    `session_id` MUST be the session the token was minted for: the JWT carries a
    `ces_session` claim naming exactly one session, so connecting under any other
    session name is permission_denied -- a failure of the harness, not of the design.

    Returns (verdict, detail). A verdict of AUDIO OK means the server accepted both
    the connection and an audio frame -- the only outcome that makes direct-connect
    viable for voice.
    """
    try:
        async with websockets.connect(
            uri or BIDI_URI,
            additional_headers=headers or {},
            subprotocols=subprotocols,
            open_timeout=20,
        ) as ws:
            await ws.send(config_frame(session_id, token if in_config else None))
            await ws.send(json.dumps({"realtimeInput": {"audio": SILENCE}}))

            # A rejection surfaces as a close frame rather than a message, so a
            # timeout waiting for data is the *good* case: the socket stayed open.
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                return "AUDIO OK", f"server replied: {str(msg)[:200]}"
            except asyncio.TimeoutError:
                return "AUDIO OK", "socket held open past the audio frame, no rejection"
    except websockets.exceptions.InvalidStatus as e:
        return "REJECTED", f"HTTP {e.response.status_code} at handshake"
    except websockets.exceptions.ConnectionClosed as e:
        return "REJECTED", f"closed {e.code}: {e.reason or '<no reason>'}"
    except asyncio.TimeoutError:
        return "REJECTED", "handshake never completed (open_timeout)"
    except Exception as e:  # noqa: BLE001 - the spike wants every failure shape
        return "ERROR", f"{type(e).__name__}: {str(e)[:140]}"


async def main() -> None:
    if not DEPLOYMENT_ID:
        raise SystemExit("SPIKE_DEPLOYMENT_ID is required -- GenerateChatToken needs a deployment.")

    print(f"app={APP}\ndeployment={DEPLOYMENT_ID}\n")

    print("Q1  Is chat_token valid for BidiRunSession at all?")
    session_id = f"spike-{uuid.uuid4().hex[:12]}"
    token = mint_token(session_id)
    verdict, detail = await attempt(
        "header", token, session_id, headers={"Authorization": f"Bearer {token}"}
    )
    print(f"  -> {verdict}: {detail}\n")

    if verdict != "AUDIO OK":
        print("STOP. The token does not authorise audio bidi even with a header.")
        print("Direct-connect is dead for voice; the relay decision is made for you.")
        return

    # Q2 only runs if Q1 passed. Each placement is one a browser could actually use.
    print("Q2  Which presentations can a browser actually use?")
    placements = [
        ("query ?access_token=", dict(uri=f"{BIDI_URI}?access_token={token}")),
        ("query ?chat_token=", dict(uri=f"{BIDI_URI}?chat_token={token}")),
        ("subprotocol", dict(subprotocols=[f"chat_token.{token}"])),
        ("first-frame config", dict(in_config=True)),
    ]
    for label, kwargs in placements:
        # Each placement needs its own session: a token is single-session, so reusing
        # one across attempts would confound "placement rejected" with "session reused".
        fresh = f"spike-{uuid.uuid4().hex[:12]}"
        fresh_token = mint_token(fresh)
        kwargs = {k: (v.replace(token, fresh_token) if isinstance(v, str) else v)
                  for k, v in kwargs.items()}
        if "subprotocols" in kwargs:
            kwargs["subprotocols"] = [f"chat_token.{fresh_token}"]
        verdict, detail = await attempt(label, fresh_token, fresh, **kwargs)
        print(f"  {label:24s} -> {verdict}: {detail}")

    print(
        "\nAny AUDIO OK above means browser-direct is viable and the relay is optional.\n"
        "All rejected means the relay stays for browsers -- but native mobile can still\n"
        "go direct over gRPC, where headers are available."
    )


if __name__ == "__main__":
    asyncio.run(main())
