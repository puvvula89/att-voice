"""Drive the deployed phone-upgrade agent on Agent Engine end-to-end.

Connects to the live bidi endpoint, scripts the full flow with text turns, and
verifies all four screens (line_selector, phone_options, confirmation, receipt)
come back as pending_ui in the bidiStreamOutput events — proving the agent runs
on Agent Engine, calls the Cloud Run MCP tools, and delivers the UI over bidi.

    export SSL_CERT_FILE=$(python -m certifi)
    python deploy/probe_agent_engine.py
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

TURNS = [
    ("start", "I want to upgrade my phone"),
    ("line_selector", "Let's do the line ending 1243"),
    ("phone_options", "I'll take the iPhone 17"),
    ("confirmation", "Yes, place the order"),
]


def _pending_ui(ev: dict):
    delta = (ev.get("actions") or {}).get("stateDelta") or {}
    return delta.get("pending_ui")


async def main():
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    ui, audio = [], 0
    turn_idx = 0
    print("Connecting to:", NAME)
    async with client.aio.live.agent_engines.connect(
        agent_engine=NAME,
        config={"class_method": "bidi_stream_query", "include_all_fields": True},
    ) as conn:
        await conn.send({"user_id": "probe"})
        await conn.send({"type": "user_action", "selection": TURNS[0][1]})

        async def drive():
            nonlocal turn_idx, audio
            while True:
                resp = await conn.receive()
                if not resp:
                    break
                ev = resp.get("bidiStreamOutput", {}) if isinstance(resp, dict) else {}
                content = ev.get("content") or {}
                for part in content.get("parts") or []:
                    if part.get("inlineData"):
                        audio += 1
                p = _pending_ui(ev)
                if p:
                    stage = p.get("stage_intent")
                    ui.append(stage)
                    print("  screen:", stage)
                    if turn_idx + 1 < len(TURNS) and TURNS[turn_idx + 1][0] == stage:
                        turn_idx += 1
                        await conn.send({"type": "user_action", "selection": TURNS[turn_idx][1]})
                if "receipt" in ui:
                    break

        try:
            await asyncio.wait_for(drive(), timeout=180)
        except asyncio.TimeoutError:
            print("TIMEOUT (reached:", ui, ")")

    print("\nUI EVENTS:", ui)
    print("AUDIO CHUNKS:", audio)
    ok = {"line_selector", "phone_options", "confirmation", "receipt"} <= set(ui) and audio > 0
    print("RESULT:", "PASS (agent on Agent Engine drives full flow + audio via bidi)" if ok else "CHECK")


asyncio.run(main())
