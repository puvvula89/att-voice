"""Protocol-faithful AudioCodes VoiceAI Connect smoke client.

Impersonates VAIC against the relay's /audiocodes-ws route so the gateway can be
exercised end-to-end WITHOUT a live VAIC tenant: it does the session.initiate ->
session.accepted handshake, streams a 16 kHz WAV as userStream.chunk frames, and
collects the bot's playStream audio (the agent's reply), then hangs up.

Run against a local relay or the deployed URL:

    python tests/smoke/smoke_audiocodes.py --url ws://localhost:8080/audiocodes-ws
    python tests/smoke/smoke_audiocodes.py --url wss://<host>/audiocodes-ws

Set AUDIOCODES_TOKEN in the env to send the Bearer token the deployed route
expects. Writes the agent's audio reply to _audiocodes_reply.wav if any arrives.
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_16k.wav")
CHUNK_MS = 20  # VAIC streams ~20 ms frames


def _load_pcm16(path):
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


async def main(url: str, seconds: float):
    pcm, rate = _load_pcm16(SAMPLE)
    headers = {}
    token = os.environ.get("AUDIOCODES_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.initiate",
            "conversationId": "smoke-conv-1",
            "botName": "att-steering",
            "caller": "+15555550100",
            "expectAudioMessages": True,
            "supportedMediaFormats": ["raw/lpcm16", "raw/lpcm16_24"],
        }))
        accepted = json.loads(await ws.recv())
        print("<-", accepted)
        assert accepted.get("type") == "session.accepted", accepted

        play_pcm = bytearray()
        seen = {}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")
                seen[t] = seen.get(t, 0) + 1
                if t == "playStream.chunk":
                    play_pcm.extend(base64.b64decode(msg["audioChunk"]))
                elif t in ("session.accepted", "userStream.started",
                           "userStream.stopped", "playStream.start",
                           "playStream.stop", "activities"):
                    print("<-", {k: msg[k] for k in msg if k != "audioChunk"})

        rtask = asyncio.create_task(reader())

        # Stream the caller utterance as userStream.chunk frames @16k linear.
        await ws.send(json.dumps({"type": "userStream.start"}))
        frame_bytes = int(rate * CHUNK_MS / 1000) * 2  # 16-bit mono
        for off in range(0, len(pcm), frame_bytes):
            await ws.send(json.dumps({
                "type": "userStream.chunk",
                "audioChunk": base64.b64encode(pcm[off:off + frame_bytes]).decode("ascii"),
            }))
            await asyncio.sleep(CHUNK_MS / 1000)
        await ws.send(json.dumps({"type": "userStream.stop"}))

        # Let the agent reply stream back.
        await asyncio.sleep(seconds)
        await ws.send(json.dumps({"type": "session.end", "reason": "smoke done"}))
        await asyncio.sleep(0.5)
        rtask.cancel()

    print("frame counts:", seen)
    print("agent audio bytes:", len(play_pcm))
    if play_pcm:
        # session.accepted chose raw/lpcm16_24 for play-out -> 24k mono PCM16.
        with wave.open(os.path.join(HERE, "_audiocodes_reply.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(play_pcm))
        print("wrote _audiocodes_reply.wav")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8080/audiocodes-ws")
    ap.add_argument("--seconds", type=float, default=8.0, help="how long to collect the reply")
    args = ap.parse_args()
    asyncio.run(main(args.url, args.seconds))
