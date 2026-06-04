"""Verify shared-session Phase 1: a voice session resumes across reconnects.

Drives the deployed Agent Engine bidi app directly (no relay):
  1. Connect with no session_id -> capture the new session_id from session_info,
     advance to phone_options, then disconnect mid-flow.
  2. Reconnect with that session_id -> assert resumed=True, and that the agent
     continues to confirmation/receipt WITHOUT re-rendering an already-completed
     screen (line_selector) — i.e. it picked up where it left off.

    export SSL_CERT_FILE=$(python -m certifi)
    python deploy/probe_resume.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import vertexai

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
NAME = os.environ.get("AGENT_ENGINE_NAME") or (ROOT / "deploy" / ".engine_name").read_text().strip()
USER = "resume-probe"
CONNECT_CFG = {"class_method": "bidi_stream_query", "include_all_fields": True}


def _unwrap(resp):
    return resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}


def _pending(ev):
    delta = (ev.get("actions") or {}).get("stateDelta") or (ev.get("actions") or {}).get("state_delta") or {}
    p = delta.get("pending_ui")
    return p.get("stage_intent") if p else None


async def _drive(conn, turns, want, timeout=60):
    """Send the first turn, then advance one turn each time a wanted screen
    arrives. Returns (screens_seen, session_info_dict)."""
    seen, info = [], None
    pending_turns = list(turns)
    await conn.send({"type": "user_action", "selection": pending_turns.pop(0)})
    while True:
        try:
            resp = await asyncio.wait_for(conn.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            break
        if not resp:
            break
        ev = _unwrap(resp)
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "session_info":
            info = ev
            continue
        si = _pending(ev)
        if si and si not in seen:
            seen.append(si)
            if pending_turns:
                await conn.send({"type": "user_action", "selection": pending_turns.pop(0)})
        if all(w in seen for w in want):
            break
    return seen, info


async def main():
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    print("Connecting to:", NAME)

    # --- Leg 1: fresh session, advance to phone_options, then drop. ---
    async with client.aio.live.agent_engines.connect(agent_engine=NAME, config=CONNECT_CFG) as conn:
        await conn.send({"user_id": USER})  # no session_id -> fresh
        seen1, info1 = await _drive(
            conn,
            ["I want to upgrade my phone", "Let's do the line ending 1243"],
            want=["line_selector", "phone_options"],
        )
    sid = (info1 or {}).get("session_id")
    print(f"  leg1 screens={seen1} session_id={sid} resumed={(info1 or {}).get('resumed')}")
    assert sid, "no session_id returned in session_info"
    assert (info1 or {}).get("resumed") is False, "fresh session should not be 'resumed'"
    assert seen1[:2] == ["line_selector", "phone_options"], f"leg1 did not reach phone_options: {seen1}"

    # --- Leg 2: reconnect with the same session_id, continue to receipt. ---
    async with client.aio.live.agent_engines.connect(agent_engine=NAME, config=CONNECT_CFG) as conn:
        await conn.send({"user_id": USER, "session_id": sid})
        seen2, info2 = await _drive(
            conn,
            ["I'll take the iPhone 17", "Yes, place the order"],
            want=["confirmation", "receipt"],
        )
    print(f"  leg2 screens={seen2} resumed={(info2 or {}).get('resumed')} session_id={(info2 or {}).get('session_id')}")

    ok = (
        (info2 or {}).get("resumed") is True
        and (info2 or {}).get("session_id") == sid
        and "confirmation" in seen2 and "receipt" in seen2
        and "line_selector" not in seen2  # did NOT restart the flow
    )
    print("RESULT:", "PASS (session resumed mid-flow and continued to receipt)" if ok else f"FAIL ({seen2}, info={info2})")
    sys.exit(0 if ok else 1)


asyncio.run(main())
