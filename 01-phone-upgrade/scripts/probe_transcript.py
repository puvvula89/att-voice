"""Probe: how Live transcription streams (deltas, then a cumulative final).

Prints each output_transcription event from the greeting so you can see that
finished=False chunks are fragments and the finished=True chunk is the whole
utterance — the reason the relay appends deltas and replaces on final.

Run from the module root:
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/probe_transcript.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
    session = await svc.create_session(app_name="probe", user_id="u1")
    runner = Runner(app_name="probe", agent=upgrade_agent, session_service=svc)
    q = LiveRequestQueue()
    cfg = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )
    q.send_content(types.Content(role="user", parts=[types.Part(text="(call_start)")]))

    async def run():
        async for ev in runner.run_live(user_id="u1", session_id=session.id,
                                        live_request_queue=q, run_config=cfg):
            ot = getattr(ev, "output_transcription", None)
            if ot is not None:
                print(f"[OUT] finished={ot.finished!r} text={ot.text!r}")
            if getattr(ev, "turn_complete", False):
                print("[turn_complete]")
                break

    try:
        await asyncio.wait_for(run(), timeout=60)
    except asyncio.TimeoutError:
        print("TIMEOUT")
    finally:
        q.close()


asyncio.run(main())
