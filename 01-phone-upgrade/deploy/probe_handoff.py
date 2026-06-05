"""Cross-channel handoff probe: start in VOICE, resume in CHAT by user_id.

Proves the Phase-2 goal end-to-end against the deployed engines:
  - separate engines (voice bidi + chat async_stream),
  - ONE shared session store (both at SESSION_ENGINE_ID),
  - cross-model resume (a Live voice session continued by a text chat model).

  Leg 1 (voice, bidi): connect to the voice engine with a fresh uuid user_id (no
    session_id), advance line_selector -> phone_options, then drop. Capture the
    session_id the engine created.
  Leg 2 (chat, async_stream): call the chat engine's async_stream_query with the
    SAME user_id and NO session_id. It must resume the voice session — same
    session_id, resumed=True, and session_info.pending_ui == phone_options (the
    screen carried over). Then drive two text turns to confirmation -> receipt,
    WITHOUT re-rendering the already-completed line_selector.

    export SSL_CERT_FILE=$(python -m certifi)
    python deploy/probe_handoff.py
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import vertexai

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
VOICE_NAME = os.environ.get("AGENT_ENGINE_NAME") or (ROOT / "deploy" / ".engine_name").read_text().strip()
CHAT_NAME = (ROOT / "deploy" / ".chat_engine_name").read_text().strip()
USER = f"handoff-probe-{uuid.uuid4()}"
BIDI_CFG = {"class_method": "bidi_stream_query", "include_all_fields": True}


def _unwrap(resp):
    return resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}


def _pending(ev):
    actions = ev.get("actions") or {}
    delta = actions.get("stateDelta") or actions.get("state_delta") or {}
    p = delta.get("pending_ui")
    return p.get("stage_intent") if p else None


async def voice_leg(client):
    """Fresh voice session -> advance to phone_options -> drop. Returns (sid, seen)."""
    seen, sid = [], None
    turns = ["I want to upgrade my phone", "Let's do the line ending 1243"]
    async with client.aio.live.agent_engines.connect(agent_engine=VOICE_NAME, config=BIDI_CFG) as conn:
        await conn.send({"user_id": USER})  # no session_id -> fresh
        await conn.send({"type": "user_action", "selection": turns.pop(0)})
        while True:
            try:
                resp = await asyncio.wait_for(conn.receive(), timeout=60)
            except asyncio.TimeoutError:
                break
            if not resp:
                break
            ev = _unwrap(resp)
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "session_info":
                sid = ev.get("session_id")
                continue
            si = _pending(ev)
            if si and si not in seen:
                seen.append(si)
                if turns:
                    await conn.send({"type": "user_action", "selection": turns.pop(0)})
            if "phone_options" in seen:
                break
    return sid, seen


async def chat_leg(client):
    """Resume by user_id over chat -> continue to receipt. Returns (info, seen)."""
    agent = client.agent_engines.get(name=CHAT_NAME)
    seen, info = [], None

    async def drive(message, session_id):
        nonlocal info
        kwargs = {"user_id": USER, "message": message}
        if session_id:
            kwargs["session_id"] = session_id
        async for ev in agent.async_stream_query(**kwargs):
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "session_info":
                if info is None:          # keep the FIRST (opening-turn) session_info
                    info = ev
                continue
            si = _pending(ev)
            if si and si not in seen:
                seen.append(si)

    # Opening turn: resume by user_id only (the handoff). No session_id.
    await drive("(call_start)", None)
    sid = (info or {}).get("session_id")
    # Continue the flow by text.
    await drive("I'll take the iPhone 17", sid)
    await drive("Yes, place the order", sid)
    return (info or {}), seen


async def main():
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    print("Voice engine:", VOICE_NAME)
    print("Chat  engine:", CHAT_NAME)
    print("user_id:", USER)

    sid, seen1 = await voice_leg(client)
    print(f"  leg1 (voice) screens={seen1} session_id={sid}")
    assert sid, "voice leg produced no session_id"
    assert seen1[:2] == ["line_selector", "phone_options"], f"voice leg did not reach phone_options: {seen1}"

    info, seen2 = await chat_leg(client)
    resumed_sid = info.get("session_id")
    resumed = info.get("resumed")
    carried = (info.get("pending_ui") or {}).get("stage_intent")
    print(f"  leg2 (chat) resumed={resumed} session_id={resumed_sid} carried_screen={carried} new_screens={seen2}")

    ok = (
        resumed is True
        and resumed_sid == sid          # SAME session across engines/channels
        and carried == "phone_options"  # the voice screen carried over to chat
        and "confirmation" in seen2 and "receipt" in seen2
        and "line_selector" not in seen2  # did NOT restart the completed flow
    )
    print("RESULT:", "PASS (voice session resumed in chat and continued to receipt)"
          if ok else f"FAIL (resumed={resumed}, sid match={resumed_sid == sid}, carried={carried}, seen2={seen2})")
    sys.exit(0 if ok else 1)


asyncio.run(main())
