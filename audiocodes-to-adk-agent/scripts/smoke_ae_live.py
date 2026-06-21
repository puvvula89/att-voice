from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import wave

from relay.agents_runtime.ae_live import AeAdkSession
from relay.session_record import SessionRecord


async def main():
    sess = AeAdkSession(
        engine=os.environ["AE_ENGINE_ID"],
        agent_key="greeter",
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    record = SessionRecord(session_id=None, caller="+15550000000")
    await sess.open(record)

    # Stream a 16kHz mono PCM16 WAV (say "my internet is down").
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
        if len(seen) > 12:
            break
    await sess.close()
    print("session_id:", record.session_id)
    print("events:", seen)


asyncio.run(main())
