"""Live smoke test: one user turn drives tools -> ui_event -> audio, then the
agent waits (does not auto-advance).

Sends "I want to upgrade my phone" and watches the agent call get_lines ->
render_component("line_selector"), emit a pending_ui state delta, and produce
audio. Then confirms it WAITS after line_selector instead of barreling ahead.

Run from the module root:
    export SSL_CERT_FILE=$(python -m certifi)
    python scripts/smoke_flow.py
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


async def main():
    svc = InMemorySessionService()
    session = await svc.create_session(app_name="flow", user_id="u1")
    runner = Runner(app_name="flow", agent=upgrade_agent, session_service=svc)
    q = LiveRequestQueue()
    cfg = RunConfig(streaming_mode=StreamingMode.BIDI, response_modalities=["AUDIO"])
    q.send_content(types.Content(role="user",
                   parts=[types.Part(text="I want to upgrade my phone")]))

    tool_calls, ui, audio_chunks = [], [], 0

    async def run():
        nonlocal audio_chunks
        async for ev in runner.run_live(user_id="u1", session_id=session.id,
                                        live_request_queue=q, run_config=cfg):
            for fc in (ev.get_function_calls() or []):
                tool_calls.append((fc.name, dict(fc.args or {})))
            if ev.actions and getattr(ev.actions, "state_delta", None):
                p = ev.actions.state_delta.get("pending_ui")
                if p:
                    ui.append(p.get("stage_intent"))
            if ev.content and ev.content.parts:
                for part in ev.content.parts:
                    if getattr(part, "inline_data", None):
                        audio_chunks += 1
            # Stop ~when the first screen is up; gives the model room to (wrongly) advance.
            if ui and audio_chunks > 0 and getattr(ev, "turn_complete", False):
                break

    try:
        await asyncio.wait_for(run(), timeout=75)
    except asyncio.TimeoutError:
        print("RESULT: TIMEOUT")
    except Exception as e:
        print("RESULT: ERROR ->", type(e).__name__, str(e)[:400])
        q.close(); return
    finally:
        q.close()

    print("TOOL CALLS:", [c[0] for c in tool_calls])
    print("UI EVENTS (stage_intents):", ui)
    print("AUDIO CHUNKS:", audio_chunks)
    names = [c[0] for c in tool_calls]
    advanced = "get_eligible_phones" in names or any(
        c[0] == "render_component" and c[1].get("stage_intent") == "phone_options" for c in tool_calls)
    ok = ("line_selector" in ui) and audio_chunks > 0 and not advanced
    print("RESULT:", "PASS (rendered line_selector + audio, then waited)" if ok
          else "CHECK (advanced too far or missing audio/ui)")


asyncio.run(main())
