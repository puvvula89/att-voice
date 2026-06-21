"""Smoke test for the CES BidiRunSession adapter (relay.agent_channels.CesBidiSession).

Streams a 16kHz mono PCM16 WAV, then continuous SILENCE so CES endpointing can
detect end-of-speech (in a real call audio flows continuously; a test that stops
sending audio never triggers the endpointer and the session times out after 30s).

Run from the module root:  python tests/smoke/smoke_ces_bidi.py
"""
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import asyncio

from relay.agent_channels import CesBidiSession
from relay.call_session import SessionRecord

WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_16k.wav")
SILENCE = b"\x00" * 640  # 320 samples * 2 bytes = 20ms @ 16kHz


async def _pump(sess):
    """Stream the WAV at realtime pace, then keep sending silence frames."""
    with wave.open(WAV, "rb") as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2
        while True:
            frames = w.readframes(320)
            if not frames:
                break
            await sess.send_audio(frames)
            await asyncio.sleep(0.02)
    while True:  # trailing silence so the endpointer fires
        await sess.send_audio(SILENCE)
        await asyncio.sleep(0.02)


async def main():
    app = os.environ["CES_APP"]
    sess = CesBidiSession(app=app, location=os.environ.get("CES_LOCATION", "us"))
    record = SessionRecord(session_id=None, caller="+15550000000")
    record.set_intent("billing")
    record.add_turn("user", "I have a question about my bill")
    await sess.open(record)

    pump = asyncio.create_task(_pump(sess))
    user_transcript = None
    agent_text = ""
    audio_chunks = 0
    seen = []
    try:
        async for ev in sess.events():
            name = type(ev).__name__
            seen.append(name)
            if name == "AgentTranscript" and getattr(ev, "role", "") == "user":
                user_transcript = ev.text
            elif name == "AgentTranscript" and getattr(ev, "role", "") == "agent":
                agent_text = ev.text
            elif name == "AgentAudio":
                audio_chunks += 1
            # stop once the agent has produced a reply + some audio
            if agent_text and audio_chunks >= 3:
                break
            if len(seen) > 200:
                break
    finally:
        pump.cancel()
        await sess.close()

    print("user transcript:", user_transcript)
    print("agent text     :", (agent_text[:160] + "…") if len(agent_text) > 160 else agent_text)
    print("agent audio chunks:", audio_chunks)
    ok = bool(user_transcript) and bool(agent_text) and audio_chunks > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


asyncio.run(main())
