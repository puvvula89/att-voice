"""Mint a chat token, decode it locally, and read the server's full rejection.

The first spike run closed with `1008 ... Audience mismatch. Audience should be one
of` -- truncated mid-sentence. That is not "the token cannot do bidi"; it is the
server naming the audiences the token IS good for. Both halves of the answer are in
reach cheaply:

  * The token is a JWT, so its claims decode offline -- no network, no quota.
  * The close reason names the accepted audiences, so one connection buys the rest.

Decoding is signature-free on purpose: we are reading claims we already own, not
trusting the token for anything.
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

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "ivr-and-app-voice")
DEPLOYMENT_ID = os.environ.get("SPIKE_DEPLOYMENT_ID", "spike")

APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
BIDI_URI = (
    "wss://ces.googleapis.com/ws/"
    "google.cloud.ces.v1beta.SessionService/BidiRunSession/locations/" + LOCATION
)


def decode_segment(segment: str) -> dict:
    """Base64url-decode one JWT segment, restoring the stripped padding."""
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def main() -> None:
    session_id = f"spike-{uuid.uuid4().hex[:12]}"
    client = ces.WidgetServiceClient(
        client_options=ClientOptions(api_endpoint="ces.googleapis.com")
    )
    resp = client.generate_chat_token(
        request=ces.GenerateChatTokenRequest(
            name=f"{APP}/sessions/{session_id}",
            deployment=f"{APP}/deployments/{DEPLOYMENT_ID}",
        )
    )
    token = resp.chat_token
    print(f"token length: {len(token)}  segments: {token.count('.') + 1}")

    parts = token.split(".")
    if len(parts) == 3:
        print("\n--- JWT header ---")
        print(json.dumps(decode_segment(parts[0]), indent=2))
        print("\n--- JWT claims ---")
        print(json.dumps(decode_segment(parts[1]), indent=2))
    else:
        print("\nNot a three-segment JWT; opaque token. First 60 chars:")
        print(" ", token[:60])

    print("\n--- full server rejection ---")

    async def probe() -> None:
        try:
            async with websockets.connect(
                BIDI_URI,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=20,
            ) as ws:
                await ws.send(json.dumps({"config": {"session": f"{APP}/sessions/{session_id}"}}))
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                print("  ACCEPTED:", str(msg)[:300])
        except websockets.exceptions.ConnectionClosed as e:
            print(f"  close code : {e.code}")
            print(f"  close reason: {e.reason}")
        except Exception as e:  # noqa: BLE001 - want every failure shape intact
            print(f"  {type(e).__name__}: {e}")

    asyncio.run(probe())


if __name__ == "__main__":
    main()
