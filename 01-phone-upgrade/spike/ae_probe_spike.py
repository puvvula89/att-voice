"""Connect to the deployed spike bidi app and inspect the receive() shape.

Sends one request and prints each received message verbatim, then reports
whether the nested `actions.state_delta.pending_ui` (with its options list)
survived the bidi transport intact.

    python spike/ae_probe_spike.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vertexai

PROJECT = "REDACTED_PROJECT"
LOCATION = "us-central1"
NAME = (ROOT / "spike" / ".engine_name").read_text().strip()

client = vertexai.Client(project=PROJECT, location=LOCATION)


def _find_pending_ui(obj):
    """Recursively search for a dict carrying our pending_ui marker."""
    if isinstance(obj, dict):
        if "pending_ui" in obj and isinstance(obj["pending_ui"], dict):
            return obj["pending_ui"]
        for v in obj.values():
            hit = _find_pending_ui(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_pending_ui(v)
            if hit is not None:
                return hit
    return None


async def main():
    print("Connecting to:", NAME)
    received = []
    async with client.aio.live.agent_engines.connect(
        agent_engine=NAME,
        config={"class_method": "bidi_stream_query", "include_all_fields": True},
    ) as conn:
        await conn.send({"input": "ping"})
        for _ in range(4):
            try:
                msg = await asyncio.wait_for(conn.receive(), timeout=20)
            except asyncio.TimeoutError:
                print("(timeout waiting for more messages)")
                break
            received.append(msg)
            print("--- received ---")
            print(json.dumps(msg, indent=2, default=str)[:1200])
            if isinstance(msg, dict) and _find_pending_ui(msg) is None and "_end" in json.dumps(msg, default=str):
                break

    pui = _find_pending_ui(received)
    print("\n==== VERDICT ====")
    if pui and isinstance(pui.get("options"), list) and pui.get("stage_intent") == "demo":
        print("PASS: nested pending_ui survived intact ->", json.dumps(pui, default=str)[:300])
        print("Topology B viable: relay can extract pending_ui from AE bidi output.")
    elif pui:
        print("PARTIAL: pending_ui found but altered ->", json.dumps(pui, default=str)[:300])
    else:
        print("FAIL: no intact nested pending_ui in any received message.")
        print("AE bidi flattened/dropped the structured state_delta — Topology B needs another UI channel.")


asyncio.run(main())
