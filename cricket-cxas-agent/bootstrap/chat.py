"""Run a scripted text conversation against the draft app and print each turn.

    .venv/bin/python bootstrap/chat.py "my wifi is really slow" "yes" "walk me through it"
    .venv/bin/python bootstrap/chat.py --session <id> "ready"     # continue a session

Prints the agent's words and every tool call per turn. This is the typed M1
surface: the fastest way to exercise reasoning and tool selection. It is a
development surface, not a delivered channel; voice is tuned in M2.
"""
import json
import sys
import time

from google.api_core import exceptions as gax
from cxas_scrapi.core.sessions import Sessions

from common import APP


def _walk(obj, found):
    """Collect Tool spans (name, args, result) and LLM fallbacks from the diagnostic tree."""
    if isinstance(obj, dict):
        attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else None
        if obj.get("name") == "Tool" and attrs:
            found.append(("tool", attrs.get("name"), {"args": attrs.get("args"), "result": attrs.get("result") or attrs.get("response")}))
        if obj.get("name") == "LLM" and attrs and ("fallback reason" in attrs or "undeclared tool references" in attrs):
            found.append(("llm", attrs.get("agent"), {k: v for k, v in attrs.items() if k in ("fallback reason", "unexpected function call", "undeclared tool references")}))
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def _raw(res) -> dict:
    """Marshal the response without the SDK helper, which trips on fields newer than it."""
    from google.protobuf.json_format import MessageToDict
    try:
        return MessageToDict(res._pb, preserving_proto_field_name=False)
    except Exception:  # noqa: BLE001
        return {"_str": str(res)[:4000]}


def _run_with_retry(sessions, session_id, text, attempts=4):
    for i in range(attempts):
        try:
            return sessions.run(session_id, text=text)
        except gax.ResourceExhausted:
            wait = 15 * (i + 1)
            print(f"  (429 quota; retry in {wait}s)")
            time.sleep(wait)
    return None


def main():
    args = sys.argv[1:]
    sessions = Sessions(app_name=APP)
    if args and args[0] == "--session":
        session_id, args = args[1], args[2:]
    else:
        session_id = sessions.create_session_id()
    print(f"session {session_id}")
    for text in [a for a in args if a != "--raw"]:
        print(f"\n> {text}")
        res = _run_with_retry(sessions, session_id, text)
        if res is None:
            print("agent: (no response: quota exhausted after retries)")
            continue
        outputs = getattr(res, "outputs", None) or []
        try:
            print(f"agent: {sessions.get_agent_text_from_outputs(outputs).strip()}")
        except Exception:  # noqa: BLE001
            print("agent: (no text)")
        raw = _raw(res)
        found = []
        _walk(raw, found)
        for kind, name, payload in found:
            short = json.dumps(payload, default=str)[:220] if payload is not None else ""
            print(f"  [{kind}] {name} {short}")
        if "--raw" in sys.argv:
            print(json.dumps(raw, indent=1, default=str)[:4000])
    print(f"\n(continue with --session {session_id})")


if __name__ == "__main__":
    main()
