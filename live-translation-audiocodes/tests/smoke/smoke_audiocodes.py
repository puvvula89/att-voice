"""Fake VoiceAI Connect client for exercising the bridge without a phone call.

Performs the session.initiate handshake, streams a 16 kHz WAV as userStream.chunk
frames in real time, collects playStream audio, then ends the session.

    python tests/smoke/smoke_audiocodes.py --url ws://localhost:8080/audiocodes-ws
    python tests/smoke/smoke_audiocodes.py --wav path/to/spanish_16k.wav

Set AUDIOCODES_TOKEN to send the Bearer token. Writes the returned audio to
_reply.wav next to this script.
"""
import argparse
import asyncio
import base64
import json
import os
import wave

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK_MS = 20


async def main(url: str, wav_path: str, seconds: float):
    with wave.open(wav_path, "rb") as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    assert rate == 16000, f"expected 16 kHz WAV, got {rate}"
    headers = {}
    if os.environ.get("AUDIOCODES_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['AUDIOCODES_TOKEN']}"

    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.initiate",
            "conversationId": "smoke-conv-1",
            "caller": "+15555550100",
            "expectAudioMessages": True,
            "supportedMediaFormats": ["raw/lpcm16", "raw/lpcm16_24"],
        }))
        accepted = json.loads(await ws.recv())
        print("<-", accepted)
        assert accepted.get("type") == "session.accepted", accepted

        play_pcm = bytearray()
        seen: dict = {}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")
                seen[t] = seen.get(t, 0) + 1
                if t == "playStream.chunk":
                    play_pcm.extend(base64.b64decode(msg["audioChunk"]))

        rtask = asyncio.create_task(reader())
        await ws.send(json.dumps({"type": "userStream.start"}))
        frame = int(rate * CHUNK_MS / 1000) * 2
        for off in range(0, len(pcm), frame):
            await ws.send(json.dumps({
                "type": "userStream.chunk",
                "audioChunk": base64.b64encode(pcm[off:off + frame]).decode("ascii"),
            }))
            await asyncio.sleep(CHUNK_MS / 1000)
        # VoiceAI Connect keeps streaming silence after speech; do the same.
        silence = base64.b64encode(bytes(frame)).decode("ascii")
        for _ in range(int(seconds * 1000 / CHUNK_MS)):
            await ws.send(json.dumps({"type": "userStream.chunk", "audioChunk": silence}))
            await asyncio.sleep(CHUNK_MS / 1000)
        await ws.send(json.dumps({"type": "userStream.stop"}))
        await ws.send(json.dumps({"type": "session.end", "reason": "smoke done"}))
        await asyncio.sleep(0.5)
        rtask.cancel()

    print("frame counts:", seen)
    print("playback bytes:", len(play_pcm))
    if play_pcm:
        with wave.open(os.path.join(HERE, "_reply.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(play_pcm))
        print("wrote _reply.wav")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8080/audiocodes-ws")
    ap.add_argument("--wav", default=os.path.join(HERE, "sample_16k.wav"))
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()
    asyncio.run(main(args.url, args.wav, args.seconds))
