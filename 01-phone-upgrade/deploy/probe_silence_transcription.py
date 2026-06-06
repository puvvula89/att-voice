"""Does the voice engine HALLUCINATE input_transcription on non-speech audio?

Reproduces the "ad copy I never said" bug. Connects to the voice Agent Engine
bidi (no relay/UI), lets the greeting play, then streams ~20s of NON-SPEECH audio
(digital silence, then a faint mic-noise floor) at real-time pace — exactly what an
idle, un-gated mic sends when the user isn't talking — and prints every
input_transcription the engine emits. Any text here is fabricated: nothing was
spoken. Confirms whether the stray transcript was an ASR hallucination on silence
(vs. real room audio the mic happened to capture).

    export SSL_CERT_FILE=$(python -m certifi)
    python deploy/probe_silence_transcription.py
"""
import asyncio
import base64
import os
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import vertexai  # noqa: E402

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
ENGINE = os.environ.get("AGENT_ENGINE_NAME") or (ROOT / "deploy" / ".engine_name").read_text().strip()

RATE = 16000
FRAME_MS = 100
FRAME_SAMPLES = RATE * FRAME_MS // 1000      # 1600
STREAM_SECONDS = 20


def frame(amplitude: int) -> str:
    """One 100 ms PCM16 frame. amplitude=0 → digital silence; small → noise floor."""
    if amplitude == 0:
        pcm = b"\x00\x00" * FRAME_SAMPLES
    else:
        pcm = struct.pack(
            f"<{FRAME_SAMPLES}h",
            *[random.randint(-amplitude, amplitude) for _ in range(FRAME_SAMPLES)],
        )
    return base64.b64encode(pcm).decode()


async def main():
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    in_tr, out_tr = [], []
    print("Engine:", ENGINE)
    async with client.aio.live.agent_engines.connect(
        agent_engine=ENGINE,
        config={"class_method": "bidi_stream_query", "include_all_fields": True},
    ) as conn:
        await conn.send({"user_id": f"silence-probe-{random.randint(1000,9999)}"})

        async def collect():
            while True:
                resp = await conn.receive()
                if not resp:
                    break
                ev = resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}
                if not isinstance(ev, dict):
                    continue
                it = ev.get("inputTranscription") or ev.get("input_transcription")
                ot = ev.get("outputTranscription") or ev.get("output_transcription")
                if it and it.get("text"):
                    in_tr.append(it["text"])
                    print(f"  !! INPUT_TRANSCRIPTION (nothing was spoken): {it['text']!r}")
                if ot and ot.get("text"):
                    out_tr.append(ot["text"])

        async def stream_nonspeech():
            # let the greeting come first
            await asyncio.sleep(4)
            print(f"-- streaming {STREAM_SECONDS}s of DIGITAL SILENCE (amplitude 0)…")
            for _ in range(STREAM_SECONDS * 1000 // FRAME_MS):
                await conn.send({"type": "audio", "data": frame(0)})
                await asyncio.sleep(FRAME_MS / 1000)
            print(f"-- streaming {STREAM_SECONDS}s of FAINT NOISE FLOOR (amplitude ~60)…")
            for _ in range(STREAM_SECONDS * 1000 // FRAME_MS):
                await conn.send({"type": "audio", "data": frame(60)})
                await asyncio.sleep(FRAME_MS / 1000)
            print(f"-- streaming {STREAM_SECONDS}s of LOUD NOISE (amplitude ~9000, VAD-triggering energy)…")
            for _ in range(STREAM_SECONDS * 1000 // FRAME_MS):
                await conn.send({"type": "audio", "data": frame(9000)})
                await asyncio.sleep(FRAME_MS / 1000)
            await asyncio.sleep(3)  # let any trailing transcription flush

        collector = asyncio.create_task(collect())
        try:
            await asyncio.wait_for(stream_nonspeech(), timeout=STREAM_SECONDS * 2 + 30)
        except asyncio.TimeoutError:
            pass
        collector.cancel()

    print("\n=== RESULT ===")
    print("output transcription (greeting, expected):", " ".join(out_tr)[:160] or "(none)")
    if in_tr:
        print(f"\nHALLUCINATED input transcriptions on non-speech ({len(in_tr)}):")
        for t in in_tr:
            print("  -", repr(t))
        print("\n=> The engine fabricates input_transcription from silence/noise. The stray")
        print("   'ad' line was an ASR hallucination on the idle mic stream — not something said.")
    else:
        print("\nNo input_transcription on non-speech in this run. The stray line was more likely")
        print("real ambient audio the open mic captured (or hallucination is intermittent).")


if __name__ == "__main__":
    asyncio.run(main())
