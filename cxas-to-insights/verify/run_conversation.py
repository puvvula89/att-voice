"""Drive a real LIVE conversation against the deployed app, then wait for it to
land in CES conversation history.

Why this and not the simulator: a conversation started from the CX Agent Studio
simulator is recorded with `Conversation.source = SIMULATOR`. Calling
SessionService.RunSession over the API produces `source = LIVE`, which is what
Insights reports on. Verified: a simulator conversation will not show up in
Insights no matter how the app is configured.

Run:
    python verify/run_conversation.py
"""
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ces_client import APP, APP_ID, CES_ROOT, call  # noqa: E402

DEPLOYMENT_ID = "deploy-0001"

TURNS = [
    "Hello, I was overcharged on my bill this month.",
    "It is about twenty dollars more than usual. Can you check?",
    "Okay thanks, that is all. Goodbye.",
]


def say(session, deployment, text, retries=4):
    """One turn. Retries on 429 — the demo model quota is easy to exhaust."""
    body = {
        "config": {
            "session": session,
            "deployment": deployment,
            "excludeDiagnosticInfo": True,
        },
        "inputs": [{"text": text}],
    }
    for attempt in range(retries):
        r = call("POST", f"https://ces.googleapis.com/v1beta/{session}:runSession", body)
        if "__err" not in r:
            return "".join(o.get("text", "") for o in r.get("outputs", []))
        if r["__err"] != 429:
            return f"ERROR {r['__err']}: {r['__body'][:200]}"
        time.sleep(15 * (attempt + 1))
    return "ERROR: quota exhausted after retries"


def main():
    session_id = "verify-" + uuid.uuid4().hex[:12]
    session = f"{APP}/sessions/{session_id}"
    deployment = f"{APP}/deployments/{DEPLOYMENT_ID}"

    print(f"session: {session_id}\ndeployment: {DEPLOYMENT_ID}\n")
    for text in TURNS:
        print(f"USER : {text}")
        print(f"AGENT: {say(session, deployment, text)}\n")

    # The conversation is only written to history once the session completes, so
    # it does not appear instantly. Observed ~90s.
    print("Waiting for the conversation to appear in CES history...")
    deadline = time.time() + 420
    while time.time() < deadline:
        time.sleep(15)
        r = call("GET", f"{CES_ROOT}/apps/{APP_ID}/conversations")
        match = [
            c for c in r.get("conversations", [])
            if c.get("name", "").endswith(f"/{session_id}")
        ]
        if match:
            c = match[0]
            print(json.dumps({
                "conversation": c.get("name", "").split("/")[-1],
                "source": c.get("source"),
                "turnCount": c.get("turnCount"),
                "endTime": c.get("endTime"),
            }, indent=2))
            if c.get("source") != "LIVE":
                print(f"\nWARNING: source is {c.get('source')}, not LIVE. "
                      "Insights only reports on LIVE conversations.")
                return 1
            print("\nsource=LIVE. Now run: python verify/check_insights.py "
                  f"{session_id}")
            return 0
        print(f"  [{int(time.time() - deadline + 420)}s] not in history yet")

    print("Timed out. Re-run check_insights.py later; history can lag.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
