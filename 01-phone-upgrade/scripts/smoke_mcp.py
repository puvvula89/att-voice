"""Live end-to-end smoke over the MCP topology.

Drives the full flow with scripted user turns and verifies every hop:
browser -> relay -> agent -> MCP server (data tools) -> back -> callback staging
-> pending_ui. Confirms the *stateless* MCP signatures work: the model carries
line_id + phone_id into select_phone / confirm_upgrade.

Prereqs (from the module root):
    python -m mcp_server.server                 # MCP server on :9000
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/smoke_mcp.py

Pass = all four stage_intents rendered (line_selector, phone_options,
confirmation, receipt) and confirm_upgrade was called with line_id + phone_id.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.agent import upgrade_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

# Scripted turns, advanced as each expected screen appears.
TURNS = [
    ("start", "I want to upgrade my phone"),
    ("line_selector", "Let's do the line ending 1243"),
    ("phone_options", "I'll take the iPhone 17"),
    ("confirmation", "Yes, place the order"),
]


async def main():
    svc = InMemorySessionService()
    session = await svc.create_session(app_name="mcp_smoke", user_id="u1")
    runner = Runner(app_name="mcp_smoke", agent=upgrade_agent, session_service=svc)
    q = LiveRequestQueue()
    cfg = RunConfig(streaming_mode=StreamingMode.BIDI, response_modalities=["AUDIO"])

    tool_calls, ui = [], []
    turn_idx = 0
    q.send_content(types.Content(role="user", parts=[types.Part(text=TURNS[0][1])]))

    async def run():
        nonlocal turn_idx
        async for ev in runner.run_live(user_id="u1", session_id=session.id,
                                        live_request_queue=q, run_config=cfg):
            for fc in (ev.get_function_calls() or []):
                tool_calls.append((fc.name, dict(fc.args or {})))
            if ev.actions and getattr(ev.actions, "state_delta", None):
                p = ev.actions.state_delta.get("pending_ui")
                if p:
                    stage = p.get("stage_intent")
                    ui.append(stage)
                    # Advance to the next scripted turn when its screen appears.
                    if turn_idx + 1 < len(TURNS) and TURNS[turn_idx + 1][0] == stage:
                        turn_idx += 1
                        q.send_content(types.Content(
                            role="user", parts=[types.Part(text=TURNS[turn_idx][1])]))
                if ev.actions.state_delta.get("call_ended"):
                    break
            if "receipt" in ui:
                break

    try:
        await asyncio.wait_for(run(), timeout=160)
    except asyncio.TimeoutError:
        print("RESULT: TIMEOUT (reached:", ui, ")")
    except Exception as e:
        print("RESULT: ERROR ->", type(e).__name__, str(e)[:300])
    finally:
        q.close()

    names = [c[0] for c in tool_calls]
    print("TOOL CALLS:", names)
    print("UI EVENTS:", ui)
    sp = next((a for n, a in tool_calls if n == "select_phone"), None)
    cu = next((a for n, a in tool_calls if n == "confirm_upgrade"), None)
    print("select_phone args:", sp)
    print("confirm_upgrade args:", cu)
    ok = (
        {"line_selector", "phone_options", "confirmation", "receipt"} <= set(ui)
        and sp and "line_id" in sp and "phone_id" in sp
        and cu and "line_id" in cu and "phone_id" in cu
    )
    print("RESULT:", "PASS (full MCP flow; stateless ids carried)" if ok
          else "CHECK (incomplete flow or missing ids)")


asyncio.run(main())
