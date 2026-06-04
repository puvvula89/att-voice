"""Smoke-test the deployed relay (proxy mode) over its browser WebSocket.

Connects to wss://<relay>/ws/<user_id>, scripts the four-screen flow with
user_action turns, and asserts the relay forwards ui_event screens back from
the agent — proving browser -> relay -> Agent Engine -> MCP works end to end.

    RELAY_WSS=wss://host python deploy/probe_relay_ws.py
"""
import asyncio
import json
import os
import sys

import websockets

RELAY_WSS = os.environ["RELAY_WSS"].rstrip("/")
URL = f"{RELAY_WSS}/ws/relay-smoke"

TURNS = [
    "I want to upgrade my phone",
    "Let's do the line ending 1243",
    "I'll take the iPhone 17",
    "Yes, place the order",
]
EXPECT = ["line_selector", "phone_options", "confirmation", "receipt"]


async def main():
    screens = []
    audio = 0
    turn = 0
    async with websockets.connect(URL, max_size=None, open_timeout=30) as ws:
        await ws.send(json.dumps({"type": "user_action", "selection": TURNS[turn]}))
        turn += 1
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=45)
            except asyncio.TimeoutError:
                print("TIMEOUT waiting for next event", file=sys.stderr)
                break
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "ui_event":
                si = msg["stage_intent"]
                if si not in screens:
                    screens.append(si)
                    print("  screen:", si)
                    if turn < len(TURNS):
                        await ws.send(json.dumps({"type": "user_action", "selection": TURNS[turn]}))
                        turn += 1
            elif t == "session_end":
                break
            else:
                # raw forwarded event may carry audio inlineData
                parts = ((msg.get("content") or {}).get("parts")) or []
                for p in parts:
                    if (p.get("inlineData") or p.get("inline_data")):
                        audio += 1
            if screens[-4:] == EXPECT:
                break

    print("\nUI EVENTS:", screens)
    print("AUDIO CHUNKS:", audio)
    ok = screens[:4] == EXPECT
    print("RESULT:", "PASS (browser -> relay -> AE proxy delivers full flow)" if ok else "FAIL")
    sys.exit(0 if ok else 1)


asyncio.run(main())
