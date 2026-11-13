"""Save the trace of the latest conversations to traces/, one text file each.

    .venv/bin/python bootstrap/save_trace.py        # the latest conversation
    .venv/bin/python bootstrap/save_trace.py 2      # the latest two, e.g. a call and the call back

A trace lists every turn with the tools the agent called. Files are named by start time and
conversation id; one that is already saved is skipped. A call shows up a minute or so after it ends.
The caller's phone number and the network addresses of the call are blanked out.
"""
import json
import re
import subprocess
import sys

from common import APP, ROOT

CXAS = [str(ROOT / ".venv/bin/cxas"), "trace"]
ARGS = ["--app-name", APP, "--app-dir", str(ROOT / "app")]
OUT = ROOT / "traces"
PRIVATE = re.compile(r'("(?:telephony-caller-id|google-[a-z-]*address|google-session-callid)": ")[^"]*"')


def latest(count: int) -> list[dict]:
    out = subprocess.run(CXAS + ["list", *ARGS, "--source", "LIVE", "--limit", str(count), "--format", "json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out[out.index("["):])


def main():
    OUT.mkdir(exist_ok=True)
    for c in latest(int(sys.argv[1]) if len(sys.argv) > 1 else 1):
        stamp = c["start_time"][:19].replace(":", "").replace("-", "")
        path = OUT / f"{stamp}_{c['channel'].lower()}_{c['id']}.txt"
        if path.exists():
            print("already saved", path.relative_to(ROOT))
            continue
        subprocess.run(CXAS + ["get", *ARGS, "--format", "text", "--out", str(path), c["id"]],
                       capture_output=True, text=True, check=True)
        path.write_text(PRIVATE.sub(r'\1removed"', path.read_text()))
        print("saved", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
