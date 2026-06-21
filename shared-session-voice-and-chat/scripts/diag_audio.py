"""Diagnostic: inspect the audio frames the relay sends to the browser.

Runs the relay in-process, sends one user_action, and tallies the audio parts
(inlineData.data), their total base64 size, and the MIME types — useful when
debugging silent-audio issues (format / rate / encoding).

Run from the module root:
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/diag_audio.py
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

PORT = 8078
URI = f"ws://127.0.0.1:{PORT}/ws/diag-user"


async def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(60):
        if server.started:
            break
        await asyncio.sleep(0.1)
    print("SERVER STARTED:", server.started)

    total = ui_events = audio_parts = audio_bytes = 0
    mimes = set()

    try:
        async with websockets.connect(URI, max_size=None) as ws:
            await ws.send(json.dumps({"type": "user_action",
                                      "selection": "I want to upgrade my phone"}))

            async def reader():
                nonlocal total, ui_events, audio_parts, audio_bytes
                async for raw in ws:
                    total += 1
                    msg = json.loads(raw)
                    if msg.get("type") == "ui_event":
                        ui_events += 1
                        continue
                    for p in (msg.get("content") or {}).get("parts") or []:
                        idata = p.get("inlineData") or p.get("inline_data")
                        if idata and idata.get("data"):
                            audio_parts += 1
                            audio_bytes += len(idata["data"])
                            mt = idata.get("mimeType") or idata.get("mime_type")
                            if mt:
                                mimes.add(mt)

            try:
                await asyncio.wait_for(reader(), timeout=30)
            except asyncio.TimeoutError:
                pass
    except Exception as e:
        print("CLIENT ERROR:", type(e).__name__, str(e)[:300])
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=10)
        except Exception:
            pass

    print("TOTAL MESSAGES:", total)
    print("UI EVENTS:", ui_events)
    print("AUDIO PARTS (inlineData.data):", audio_parts)
    print("AUDIO BASE64 BYTES (total):", audio_bytes)
    print("AUDIO MIME TYPES:", mimes)


asyncio.run(main())
