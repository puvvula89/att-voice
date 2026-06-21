"""Local test of the Agent Engine bidi app (backend/agent_app.py) BEFORE deploy.

Drives live_agent.bidi_stream_query with a local asyncio.Queue, scripting the
full flow, and verifies the yielded events carry pending_ui for all four screens
plus audio — proving the wrapper logic works against the live model + cloud MCP.

Prereqs (from module root):
    export MCP_SERVER_URL="https://<cloud-run-mcp>/mcp"   # or local :9000
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/smoke_bidi_app.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.agent_app import live_agent

TURNS = [
    ("start", "I want to upgrade my phone"),
    ("line_selector", "Let's do the line ending 1243"),
    ("phone_options", "I'll take the iPhone 17"),
    ("confirmation", "Yes, place the order"),
]


def _pending_ui(event: dict):
    actions = event.get("actions") or {}
    delta = actions.get("stateDelta") or actions.get("state_delta") or {}
    return delta.get("pending_ui")


def _has_audio(event: dict) -> bool:
    content = event.get("content") or {}
    for part in content.get("parts") or []:
        if part.get("inlineData") or part.get("inline_data"):
            return True
    return False


async def main():
    live_agent.set_up()
    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait({"user_id": "u1"})
    turn_idx = 0
    ui, audio_chunks = [], 0
    # First turn as a user_action-style text (after the {"user_id"} setup msg).
    await q.put({"type": "user_action", "selection": TURNS[0][1]})

    async def run():
        nonlocal turn_idx, audio_chunks
        async for event in live_agent.bidi_stream_query(q):
            if _has_audio(event):
                audio_chunks += 1
            p = _pending_ui(event)
            if p:
                stage = p.get("stage_intent")
                ui.append(stage)
                if turn_idx + 1 < len(TURNS) and TURNS[turn_idx + 1][0] == stage:
                    turn_idx += 1
                    await q.put({"type": "user_action", "selection": TURNS[turn_idx][1]})
            if "receipt" in ui:
                break

    try:
        await asyncio.wait_for(run(), timeout=180)
    except asyncio.TimeoutError:
        print("RESULT: TIMEOUT (reached:", ui, ")")
    except Exception as e:
        print("RESULT: ERROR ->", type(e).__name__, str(e)[:300])

    print("UI EVENTS:", ui)
    print("AUDIO CHUNKS:", audio_chunks)
    ok = {"line_selector", "phone_options", "confirmation", "receipt"} <= set(ui) and audio_chunks > 0
    print("RESULT:", "PASS (bidi app drives full flow + audio)" if ok else "CHECK")


asyncio.run(main())
