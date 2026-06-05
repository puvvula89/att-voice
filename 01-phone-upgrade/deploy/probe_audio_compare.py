"""A/B the agent's spoken audio on two routes to localize "deep/fast" playback.

  Route 1 (DIRECT): client -> Agent Engine bidi, NO relay, NO UI. This is the raw
                    Gemini Live model output as the agent emits it.
  Route 2 (RELAY):  client -> deployed relay WebSocket (exactly what the browser
                    does) -> Agent Engine. Proves whether the relay alters audio.

For each route it captures the model's output PCM, records the DECLARED audio
mime type / sample rate (inlineData.mimeType, e.g. "audio/pcm;rate=24000"), writes
a .wav you can listen to, and prints byte/sample/duration stats. If the two WAVs
are byte-identical the transport is transparent and any pitch difference is purely
client-side playback; the declared rate is the rate the browser must play at.

  export SSL_CERT_FILE=$(python -m certifi)        # macOS
  RELAY_WSS=wss://<relay-host> python deploy/probe_audio_compare.py

Outputs: deploy/audio_direct.wav, deploy/audio_relay.wav
"""
import asyncio
import base64
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
ENGINE = os.environ.get("AGENT_ENGINE_NAME") or (ROOT / "deploy" / ".engine_name").read_text().strip()
RELAY_WSS = os.environ.get("RELAY_WSS", "").rstrip("/")

OUT_DIR = ROOT / "deploy"
FALLBACK_RATE = 24000   # model declares bare "audio/pcm" (no rate=); 24 kHz is the Live API spec
RECV_GAP = 4.0          # stop after this many seconds with no new event (end of speech)
HARD_CAP = 40.0         # absolute ceiling on a capture

# (expected_screen, text_to_send_when_it_arrives). First turn kicks off the flow.
TURNS = [
    ("start", "I want to upgrade my phone"),
    ("line_selector", "Let's do the line ending 1243"),
    ("phone_options", "I'll take the iPhone 17"),
    ("confirmation", "Yes, place the order"),
]


def decode_pcm(data) -> bytes:
    """inlineData.data may be a base64url str (JSON) or already bytes."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    s = data.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def rate_of(mime: str) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else FALLBACK_RATE


def inline_of(part: dict):
    return part.get("inlineData") or part.get("inline_data")


def write_wav(path: Path, pcm: bytes, rate: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)


def pending_ui(ev: dict):
    delta = (ev.get("actions") or {}).get("stateDelta") or (ev.get("actions") or {}).get("state_delta") or {}
    return delta.get("pending_ui")


def harvest_audio(ev: dict, pcm: bytearray, mimes: set) -> bool:
    """Pull any audio inlineData parts out of an event. Returns True if audio found."""
    got = False
    for part in ((ev.get("content") or {}).get("parts")) or []:
        idl = inline_of(part)
        if idl and idl.get("data"):
            mimes.add(idl.get("mimeType") or idl.get("mime_type") or "")
            pcm.extend(decode_pcm(idl["data"]))
            got = True
    return got


async def capture_direct():
    """Route 1 — straight to the Agent Engine bidi endpoint (no relay)."""
    import vertexai

    pcm, mimes, seen = bytearray(), set(), []
    ti = 0
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    async with client.aio.live.agent_engines.connect(
        agent_engine=ENGINE,
        config={"class_method": "bidi_stream_query", "include_all_fields": True},
    ) as conn:
        await conn.send({"user_id": "audio-direct"})
        await conn.send({"type": "user_action", "selection": TURNS[0][1]})
        start = time.monotonic()
        while time.monotonic() - start < HARD_CAP:
            try:
                resp = await asyncio.wait_for(conn.receive(), timeout=RECV_GAP)
            except asyncio.TimeoutError:
                if pcm:
                    break          # a gap with no events after speech = done
                continue
            if not resp:
                break
            ev = resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}
            if not isinstance(ev, dict):
                continue
            harvest_audio(ev, pcm, mimes)
            p = pending_ui(ev)
            if p and p.get("stage_intent") not in seen:
                seen.append(p.get("stage_intent"))
                if ti + 1 < len(TURNS) and TURNS[ti + 1][0] == p.get("stage_intent"):
                    ti += 1
                    await conn.send({"type": "user_action", "selection": TURNS[ti][1]})
    return bytes(pcm), mimes, seen


async def capture_relay():
    """Route 2 — through the deployed relay WebSocket, like the browser."""
    import websockets

    pcm, mimes, seen = bytearray(), set(), []
    ti = 0
    url = f"{RELAY_WSS}/ws/audio-relay"
    async with websockets.connect(url, max_size=None, open_timeout=30) as ws:
        await ws.send(json.dumps({"type": "start"}))
        await ws.send(json.dumps({"type": "user_action", "selection": TURNS[0][1]}))
        start = time.monotonic()
        while time.monotonic() - start < HARD_CAP:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=RECV_GAP)
            except asyncio.TimeoutError:
                if pcm:
                    break
                continue
            except websockets.ConnectionClosed:
                break
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "ui_event":
                stage = msg.get("stage_intent")
                if stage not in seen:
                    seen.append(stage)
                    if ti + 1 < len(TURNS) and TURNS[ti + 1][0] == stage:
                        ti += 1
                        await ws.send(json.dumps({"type": "user_action", "selection": TURNS[ti][1]}))
            elif t == "session_end":
                break
            else:
                harvest_audio(msg, pcm, mimes)
    return bytes(pcm), mimes, seen


def report(label, pcm, mimes, seen, path):
    declared = any(re.search(r"rate=\d+", m or "") for m in mimes)
    rate = rate_of(next(iter(mimes), "")) if mimes else FALLBACK_RATE
    samples = len(pcm) // 2
    dur = samples / rate if rate else 0
    write_wav(path, pcm, rate)
    print(f"\n[{label}]")
    print(f"  screens      : {seen}")
    print(f"  mime types   : {sorted(mimes) or ['(none seen)']}")
    print(f"  rate         : {rate} Hz  ({'declared on the wire' if declared else 'ASSUMED — not declared in mime'})")
    print(f"  bytes/samples: {len(pcm)} / {samples}")
    print(f"  duration     : {dur:.2f}s  (only correct if {rate} Hz is the true rate)")
    print(f"  wav          : {path}")
    return rate, pcm


async def main():
    print("Engine:", ENGINE)
    d_rate, d_pcm = report("DIRECT (no relay)", *await capture_direct(), OUT_DIR / "audio_direct.wav")

    if not RELAY_WSS:
        print("\nRELAY_WSS not set — skipping relay route. Set RELAY_WSS to compare.")
        return
    r_rate, r_pcm = report("RELAY (browser path)", *await capture_relay(), OUT_DIR / "audio_relay.wav")

    print("\n=== COMPARISON ===")
    print(f"  declared rate   : direct={d_rate}  relay={r_rate}  -> {'SAME' if d_rate == r_rate else 'DIFFERENT'}")
    print(f"  pcm byte length : direct={len(d_pcm)}  relay={len(r_pcm)}")
    # Same prompt → audio won't be bit-identical run-to-run, but the DECLARED RATE
    # is the load-bearing fact. If both say 24000, the browser must play at 24000.
    if d_rate == r_rate:
        print(f"\n  => Both routes declare {d_rate} Hz. The browser must create AudioBuffers at")
        print(f"     {d_rate} Hz. If audio still sounds off at that rate, it is client playback,")
        print("     not the model or the relay.")
    else:
        print("\n  => Routes DISAGREE on rate — the relay/transport is altering the audio rate.")
    print("\nListen:  open deploy/audio_direct.wav and deploy/audio_relay.wav")


if __name__ == "__main__":
    asyncio.run(main())
