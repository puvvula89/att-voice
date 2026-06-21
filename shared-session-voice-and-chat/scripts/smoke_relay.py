"""End-to-end smoke test through the FastAPI WebSocket relay.

Starts backend.server:app in-process on a test port, connects a WebSocket
client, sends a user_action, and asserts a {type:ui_event} for line_selector
(with expanded options) is delivered over the socket. Exercises the real relay
path the browser uses.

Run from the module root:
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/smoke_relay.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import uvicorn
import websockets
from backend.server import app

PORT = 8077
URI = f"ws://127.0.0.1:{PORT}/ws/test-user"


async def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(60):
        if server.started:
            break
        await asyncio.sleep(0.1)
    print("SERVER STARTED:", server.started)

    ui_event = None
    raw_count = audio = 0
    try:
        async with websockets.connect(URI, max_size=None) as ws:
            print("WS CONNECTED ->", URI)
            await ws.send(json.dumps({"type": "user_action",
                                      "selection": "I want to upgrade my phone"}))

            async def reader():
                nonlocal ui_event, raw_count, audio
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "ui_event":
                        ui_event = msg
                        return
                    if msg.get("type") in ("transcript", "session_end"):
                        continue
                    raw_count += 1
                    for p in (msg.get("content") or {}).get("parts") or []:
                        if (p.get("inlineData") or {}).get("data"):
                            audio += 1

            await asyncio.wait_for(reader(), timeout=75)
    except asyncio.TimeoutError:
        print("RESULT: TIMEOUT waiting for ui_event")
    except Exception as e:
        print("CLIENT ERROR:", type(e).__name__, str(e)[:300])
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=10)
        except Exception:
            pass

    print("RAW ADK EVENTS BEFORE ui_event:", raw_count, "| AUDIO PARTS:", audio)
    if ui_event:
        payload = ui_event.get("payload", {})
        options = payload.get("options") or []
        print("UI EVENT stage_intent:", ui_event.get("stage_intent"),
              "| options:", len(options),
              "| first header:", (options[0].get("header") if options else None))
        ok = ui_event.get("stage_intent") == "line_selector" and len(options) > 0
        print("RESULT:", "PASS - ui_event delivered over the relay" if ok
              else "CHECK - ui_event shape unexpected")
    else:
        print("RESULT: FAIL - no ui_event received over the socket")


asyncio.run(main())
