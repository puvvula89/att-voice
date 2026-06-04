"""Live smoke test: the agent greets on (call_start) before any user input.

Sends only the (call_start) nudge the relay sends on connect and asserts the
agent produces greeting audio (and prints the transcript). PASS = audio chunks > 0.

Run from the module root:
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/smoke_greeting.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 01-phone-upgrade/
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.agent import upgrade_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types


async def main():
    svc = InMemorySessionService()
    session = await svc.create_session(app_name="greet", user_id="u1")
    runner = Runner(app_name="greet", agent=upgrade_agent, session_service=svc)
    q = LiveRequestQueue()
    cfg = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    q.send_content(types.Content(role="user", parts=[types.Part(text="(call_start)")]))

    audio_chunks = 0
    transcript = []

    async def run():
        nonlocal audio_chunks
        async for ev in runner.run_live(user_id="u1", session_id=session.id,
                                        live_request_queue=q, run_config=cfg):
            if ev.content and ev.content.parts:
                for part in ev.content.parts:
                    if getattr(part, "inline_data", None):
                        audio_chunks += 1
            ot = getattr(ev, "output_transcription", None)
            if ot and ot.finished and ot.text:
                transcript.append(ot.text)
            if audio_chunks > 0 and getattr(ev, "turn_complete", False):
                break

    try:
        await asyncio.wait_for(run(), timeout=60)
    except asyncio.TimeoutError:
        print("RESULT: TIMEOUT")
    except Exception as e:
        print("RESULT: ERROR ->", type(e).__name__, str(e)[:400])
        q.close(); return
    finally:
        q.close()

    print("AUDIO CHUNKS:", audio_chunks)
    print("GREETING:", "".join(transcript).strip())
    print("RESULT:", "PASS" if audio_chunks > 0 else "FAIL (no greeting audio)")


asyncio.run(main())
