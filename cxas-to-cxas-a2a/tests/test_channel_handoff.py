"""Cross-channel handoff test for Option A (your backend maps customer -> session id).

WHAT THIS PROVES
    Leg 1 ("web")  : connect with session id X, TYPE something memorable, disconnect.
    Leg 2 ("IVR")  : reconnect with the SAME id X on a new socket and SPEAK a
                     question only answerable from leg 1.
    Control        : same spoken question on a FRESH id must NOT know the answer.

    If leg 2 answers and the control does not, then carrying the session id across
    channels resumes the conversation — which is the whole basis of Option A.

WHAT THIS DOES *NOT* PROVE
    That a real telephony integration will let you SUPPLY the session id. Here the
    "IVR" leg is simulated by our own relay, so we choose the id. On a real carrier
    path the integration may mint its own id per call, in which case you must
    capture it (customer_id -> session_id) rather than inject it. Confirm that with
    whoever owns the telephony channel before relying on this.

SETUP
    bash run_local.sh                       # relay must be on :8000
    say "my account number please" -o /tmp/q.aiff
    afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/q.aiff /tmp/q.wav
    python tests/test_channel_handoff.py

NOTE: the app rate-limits hard (resource_exhausted / 1011). Space out runs.
"""
import asyncio, base64, json, sys, uuid, wave

import websockets

RELAY = "ws://127.0.0.1:8000/session/"
SPEECH_WAV = "/tmp/q.wav"          # 16 kHz mono LE16 — see SETUP
FRAME = 1600 * 2                   # 100 ms
SILENCE = base64.b64encode(b"\x00" * FRAME).decode()

SECRET = "12345"
STATE_IT = f"My name is Wilson and my account number is {SECRET}."


async def _collect(ws, label, timeout=30):
    agent, asr = "", []
    try:
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            t = m.get("type")
            if t == "agent_delta":
                agent += m["text"]
            elif t == "transcript" and m.get("role") == "user":
                asr.append(m["text"])
            elif t == "turn_complete":
                break
            elif t in ("error", "session_end"):
                print("   !", m)
                break
    except asyncio.TimeoutError:
        print(f"   [{label}] TIMEOUT")
    if asr:
        print(f"   [{label}] heard: {asr}")
    print(f"   [{label}] agent: {agent[:160]!r}")
    return agent


async def _greet(ws):
    await ws.send(json.dumps({"type": "start"}))
    await _collect(ws, "greet")


async def _say(ws, pcm, label):
    """Stream the utterance then keep the mic open — the endpointer needs a
    continuous stream to detect end-of-speech (see README)."""
    alive = True

    async def pump():
        for i in range(0, len(pcm), FRAME):
            await ws.send(json.dumps(
                {"type": "audio", "data": base64.b64encode(pcm[i:i + FRAME]).decode()}))
            await asyncio.sleep(0.1)
        while alive:
            await ws.send(json.dumps({"type": "audio", "data": SILENCE}))
            await asyncio.sleep(0.1)

    task = asyncio.create_task(pump())
    reply = await _collect(ws, label)
    alive = False
    task.cancel()
    return reply


async def main():
    try:
        w = wave.open(SPEECH_WAV)
    except Exception:
        sys.exit(f"missing {SPEECH_WAV} — see SETUP in this file's docstring")
    pcm = w.readframes(w.getnframes())

    sid = str(uuid.uuid4())
    print("session id (the thing your backend would store per customer):", sid)

    print("\n--- LEG 1: web channel, TYPED ---")
    async with websockets.connect(RELAY + sid) as ws:
        await ws.recv()
        await _greet(ws)
        await ws.send(json.dumps({"type": "user_message", "text": STATE_IT}))
        await _collect(ws, "stated")
    print("   (disconnected — user hangs up the web app)")

    await asyncio.sleep(3)

    print("\n--- LEG 2: 'IVR' channel, SPOKEN, SAME session id ---")
    async with websockets.connect(RELAY + sid) as ws:
        await ws.recv()
        resumed = await _say(ws, pcm, "same-id")

    await asyncio.sleep(3)

    print("\n--- CONTROL: SPOKEN on a FRESH session id ---")
    async with websockets.connect(RELAY + str(uuid.uuid4())) as ws:
        await ws.recv()
        await _greet(ws)
        control = await _say(ws, pcm, "fresh-id")

    ok = SECRET in resumed
    leaked = SECRET in control
    print(f"\nRESULT  resumed={ok}  control_leaked={leaked}")
    print("PASS — session id carries across channels" if (ok and not leaked)
          else "FAIL — id alone does not resume; use history transfer instead")
    return 0 if (ok and not leaked) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
