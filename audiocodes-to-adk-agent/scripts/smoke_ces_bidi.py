from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import wave

from relay.agents_runtime.ces_bidi import CesBidiSession
from relay.session_record import SessionRecord


async def main():
    app = os.environ["CES_APP"]
    sess = CesBidiSession(app=app, location=os.environ.get("CES_LOCATION", "us"))
    record = SessionRecord(session_id=None, caller="+15550000000")
    record.set_intent("billing")
    record.add_turn("user", "I have a question about my bill")
    await sess.open(record)

    # Stream a 16kHz mono PCM16 WAV in ~20ms chunks (record a short "hello" first).
    with wave.open("scripts/sample_16k.wav", "rb") as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2
        while True:
            frames = w.readframes(320)
            if not frames:
                break
            await sess.send_audio(frames)
            await asyncio.sleep(0.02)

    seen = []
    async for ev in sess.events():
        seen.append(type(ev).__name__)
        if len(seen) > 10:
            break
    await sess.close()
    print("events:", seen)


asyncio.run(main())
