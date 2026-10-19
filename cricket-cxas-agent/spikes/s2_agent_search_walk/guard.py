"""Spike: after_tool_callback drops results for any other phone and replaces the tool answer.

It also decodes each kept result's steps into `steps_by_id` and strips steps_b64 from what the model sees.

  install <env> <with_filter: 1|0>   put the guard on spike-dstool; 0 tells the model NOT to pass a filter
  try <env> <device> <query>         one turn; print what the search returned vs what the model was given
"""
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(sys.argv[2])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
APP = f"projects/{PROJECT}/locations/us/apps/spike-dstool"

GUARD = '''
import base64
import json
import re
import zlib
from typing import Any, Optional


def after_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext,
                        tool_response: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "answer" not in tool_response:  # not a data store result (e.g. next_step): leave it alone
        return None
    device = str(callback_context.variables.get("device") or "")
    answer = str(tool_response.get("answer", ""))
    blocks = [b.strip() for b in re.split(r"\\n\\s*\\n", answer) if b.strip().startswith("[")]
    kept, seen = [], []
    steps_by_id = json.loads(callback_context.variables.get("steps_by_id") or "{}")  # keep guides already loaded
    for b in blocks:
        dev = re.search(r"^device: ?(\\S+)", b, re.M)
        tid = re.search(r"^tutorial_id: ?(\\S+)", b, re.M)
        seen.append(dev.group(1) if dev else "")
        if not (dev and tid) or dev.group(1) != device:
            continue
        enc = re.search(r"^steps_b64: ?([A-Za-z0-9_=-]+)", b, re.M)
        if enc:
            steps_by_id[tid.group(1)] = json.loads(zlib.decompress(base64.urlsafe_b64decode(enc.group(1))).decode())
        body = re.sub(r"^\\[\\d+\\] ?", "", re.sub(r"^steps_b64:.*\\n?", "", b, flags=re.M))
        kept.append("[" + str(len(kept) + 1) + "] " + body)
    callback_context.variables["steps_by_id"] = json.dumps(steps_by_id, ensure_ascii=False)
    callback_context.variables["ds_seen_devices"] = json.dumps(seen)
    callback_context.variables["ds_kept"] = str(len(kept))
    callback_context.variables["ds_input_after"] = json.dumps(input)
    if not kept:
        return {"answer": "No tutorial matched this phone. Ask the caller to describe the problem another way."}
    return {"answer": "\\n\\n".join(kept)}
'''

WITH = ("The caller's phone is {device}. When the user describes a phone problem, call search_tutorials once with "
        "their problem and set filter to exactly: device: ANY(\"{device}\"). Then reply with the titles of the "
        "results only.")
WITHOUT = ("When the user describes a phone problem, call search_tutorials once with their problem. Do not set a "
           "filter. Then reply with the titles of the results only.")


def install(with_filter):
    import google.cloud.ces_v1beta.types as T
    from google.cloud import ces_v1beta
    from google.protobuf import field_mask_pb2
    c = ces_v1beta.AgentServiceClient()
    a = c.get_agent(name=f"{APP}/agents/spike")
    a.instruction = WITH if with_filter else WITHOUT
    a.after_tool_callbacks = [T.Callback(python_code=GUARD)]
    a.before_tool_callbacks = []
    c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(
        paths=["instruction", "after_tool_callbacks", "before_tool_callbacks"]))
    print("installed, filter in instruction:", with_filter)


def try_(device, q):
    from cxas_scrapi.core.sessions import Sessions
    from google.protobuf.json_format import MessageToDict
    s = Sessions(app_name=APP)
    sid = s.create_session_id()
    for i in range(10):
        try:
            res = MessageToDict(s.run(sid, text=q, variables={"device": device})._pb)
            break
        except Exception as e:  # noqa: BLE001
            print("  retry", str(e)[:60], flush=True); time.sleep(30)
    v, reply = {}, []
    for o in res.get("outputs", []):
        if o.get("text"):
            reply.append(o["text"])
        for m in o.get("diagnosticInfo", {}).get("messages", []):
            for c in m.get("chunks", []):
                v.update(c.get("updatedVariables", {}) or {})
    steps = json.loads(v.get("steps_by_id", "{}"))
    print("tool input   ", v.get("ds_input_after"))
    print("search gave  ", v.get("ds_seen_devices"))
    print("model got    ", v.get("ds_kept"), "results;", "steps decoded for", {k[:35]: len(x) for k, x in steps.items()})
    print("model said   ", " / ".join(reply).replace("\n", " ")[:300])


if __name__ == "__main__":
    {"install": lambda: install(sys.argv[3] == "1"), "try": lambda: try_(sys.argv[3], sys.argv[4])}[sys.argv[1]]()
