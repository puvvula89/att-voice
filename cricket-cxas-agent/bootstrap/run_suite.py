"""Run the typed scenario suite and capture every turn to a shareable folder.

    .venv/bin/python bootstrap/run_suite.py                 # all scenarios in suite_a.json
    .venv/bin/python bootstrap/run_suite.py P3 P4           # a subset
    .venv/bin/python bootstrap/run_suite.py --no-reset P3   # skip the profile reseed

Writes runs/<UTC timestamp>/<scenario>.json (full transcript, tool spans, raw
responses) and runs/<UTC timestamp>/summary.md (one table, pass/fail per
scenario on the expected and forbidden tools). Zip or commit that folder to
share a run. Reuses the retry and span-walking logic from chat.py.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys
import time

from cxas_scrapi.core.sessions import Sessions

from chat import _raw, _run_with_retry, _walk
from common import APP, PROJECT, ROOT

SUITE = pathlib.Path(__file__).with_name("suite_a.json")
RUNS = ROOT / "runs"


def reset_profile(profile: str) -> str:
    """Reseed the deployed support server; returns the server's reply or an error line."""
    try:
        out = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("demo_reset.py")), profile],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return f"reset failed: {exc}"


def run_scenario(sessions: Sessions, sc: dict, do_reset: bool) -> dict:
    record = {"id": sc["id"], "title": sc.get("title", ""), "app": APP, "project": PROJECT,
              "started": dt.datetime.now(dt.timezone.utc).isoformat(), "turns": []}
    if do_reset and sc.get("reset_profile"):
        record["reset"] = reset_profile(sc["reset_profile"])
    tools_seen: list[str] = []
    # callback_turns: the first call drops after its turns and the caller rings back in a new session.
    calls = [sc["turns"]] + ([sc["callback_turns"]] if sc.get("callback_turns") else [])
    record["session_ids"] = []
    for call, text in ((c, t) for c, turns in enumerate(calls) for t in turns):
        if len(record["session_ids"]) <= call:
            if call:
                time.sleep(5)  # the dropped call's record is readable about a second after it ends
            record["session_ids"].append(sessions.create_session_id())
        session_id = record["session_ids"][call]
        res = _run_with_retry(sessions, session_id, text)
        turn = {"user": text, "call": call + 1, "agent": None, "spans": [], "raw": None}
        if res is None:
            turn["agent"] = "(no response: quota exhausted after retries)"
        else:
            outputs = getattr(res, "outputs", None) or []
            try:
                turn["agent"] = sessions.get_agent_text_from_outputs(outputs).strip()
            except Exception:  # noqa: BLE001
                turn["agent"] = "(no text)"
            raw = _raw(res)
            found: list = []
            _walk(raw, found)
            for kind, name, payload in found:
                turn["spans"].append({"kind": kind, "name": name, "payload": payload})
                if kind == "tool" and name:
                    tools_seen.append(name.removeprefix("support_"))
            turn["raw"] = raw
        record["turns"].append(turn)
        print(f"  > {text}\n  agent: {turn['agent']}")
        for s in turn["spans"]:
            print(f"    [{s['kind']}] {s['name']}")
    record["tools_seen"] = tools_seen
    missing = [t for t in sc.get("expect_tools", []) if t not in tools_seen]
    forbidden = [t for t in sc.get("forbid_tools", []) if t in tools_seen]
    record["missing_expected"] = missing
    record["forbidden_hit"] = forbidden
    record["passed"] = not missing and not forbidden
    return record


def main():
    args = sys.argv[1:]
    do_reset = "--no-reset" not in args
    wanted = [a for a in args if not a.startswith("--")]
    suite = json.loads(SUITE.read_text())["scenarios"]
    if wanted:
        suite = [s for s in suite if s["id"] in wanted]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = Sessions(app_name=APP)
    print(f"app {APP}\nwriting {out_dir}")
    rows = []
    for sc in suite:
        print(f"\n=== {sc['id']} — {sc.get('title', '')}")
        rec = run_scenario(sessions, sc, do_reset)
        (out_dir / f"{sc['id']}.json").write_text(json.dumps(rec, indent=1, default=str))
        rows.append(rec)
    lines = [f"# Typed suite run {stamp}", "", f"App `{APP}`", "",
             "| Scenario | Title | Result | Tools seen | Missing | Forbidden hit |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['title']} | {'PASS' if r['passed'] else 'FAIL'} | "
                     f"{', '.join(dict.fromkeys(r['tools_seen'])) or '-'} | "
                     f"{', '.join(r['missing_expected']) or '-'} | {', '.join(r['forbidden_hit']) or '-'} |")
    lines += ["", "## Transcripts", ""]
    for r in rows:
        lines.append(f"### {r['id']} — {r['title']} (sessions {', '.join(f'`{x}`' for x in r['session_ids'])})")
        for t in r["turns"]:
            lines.append(f"- **Caller (call {t['call']}):** {t['user']}")
            lines.append(f"  **Agent:** {t['agent']}")
            tools = [s["name"] for s in t["spans"] if s["kind"] == "tool"]
            if tools:
                lines.append(f"  _tools: {', '.join(tools)}_")
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines))
    passed = sum(r["passed"] for r in rows)
    print(f"\n{passed}/{len(rows)} scenarios passed. Summary: {out_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
