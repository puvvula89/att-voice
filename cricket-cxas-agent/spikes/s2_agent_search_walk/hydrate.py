"""Spike: resume a walk on callback from the dropped call's conversation record.

  install <env>   declare callback_note, add the callback rule to the walk instruction
  run <env>       call 1 walks up to the restart and drops; read its record; call 2 starts with that state
"""
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(sys.argv[2])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
APP = f"projects/{PROJECT}/locations/us/apps/spike-dstool"
import walk  # noqa: E402

CALLBACK = """
0. {callback_note}
   If that line is not empty, the caller is calling back: greet them, say you saved their place, and ask whether
   that step fixed the problem. If fixed, close. If not, call next_step with that tutorial_id and continue."""

CALL1 = ["wifi calling isn't working on my phone", "walk me through it", "ok", "done", "done"]
CALL2 = ["hi, I'm calling back", "no, I didn't get to finish it", "done, I rejoined the wifi"]


def install():
    import google.cloud.ces_v1beta.types as T
    from cxas_scrapi.core.variables import Variables, VariableType
    from google.cloud import ces_v1beta
    from google.protobuf import field_mask_pb2
    v = Variables(app_name=APP)
    names = {"callback_note": "Saved place from a dropped call", "walk": "Walk checkpoint",
             "steps_by_id": "Loaded tutorial steps"}
    decl = [d for d in v.get_app(APP).variable_declarations if d.name not in names]
    decl += [T.App.VariableDeclaration(name=n, description=d, schema={"type_": VariableType.STRING.value,
                                                                      "default": {"string_value": ""}})
             for n, d in names.items()]
    v.update_app(APP, variable_declarations=decl)
    c = ces_v1beta.AgentServiceClient()
    a = c.get_agent(name=f"{APP}/agents/spike")
    a.instruction = walk.INSTRUCTION.replace("1. When", CALLBACK.strip() + "\n1. When", 1)
    c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["instruction"]))
    print("installed:", [d.name for d in v.get_app(APP).variable_declarations])


def turn(s, sid, text, variables=None):
    from google.protobuf.json_format import MessageToDict
    for k in range(10):
        try:
            res = MessageToDict(s.run(sid, text=text, variables=variables)._pb)
            break
        except Exception as e:  # noqa: BLE001
            print("   (retry", str(e)[:40] + ")", flush=True); time.sleep(30)
    print(f"\n> {text}")
    for o in res.get("outputs", []):
        for m in o.get("diagnosticInfo", {}).get("messages", []):
            for c in m.get("chunks", []):
                if "toolCall" in c:
                    print("   [" + c["toolCall"].get("displayName", "") + "]", json.dumps(c["toolCall"].get("args"))[:140])
        if o.get("text"):
            print("  agent:", o["text"].replace("\n", " ")[:300], flush=True)
    time.sleep(20)


def saved_state(sid):
    """What the relay would do on callback: read the dropped call's record and take the last value of each variable."""
    from google.cloud import ces_v1beta
    from google.protobuf.json_format import MessageToDict
    conv = MessageToDict(ces_v1beta.AgentServiceClient().get_conversation(name=f"{APP}/conversations/{sid}")._pb)
    v = {}
    for t in conv.get("turns", []):
        for m in t.get("messages", []):
            for c in m.get("chunks", []):
                v.update(c.get("updatedVariables", {}) or {})
    return v


def run():
    from cxas_scrapi.core.sessions import Sessions
    s = Sessions(app_name=APP)
    sid1 = sys.argv[3] if len(sys.argv) > 3 else s.create_session_id()
    print("=== call 1", sid1)
    for i, text in enumerate(CALL1 if len(sys.argv) <= 3 else []):
        turn(s, sid1, text, {"device": "iphone-13", "callback_note": ""} if i == 0 else None)
    time.sleep(5)  # caller restarts the phone; the call drops
    v = saved_state(sid1)
    w = json.loads(v.get("walk", "{}"))
    r = w.get("resume")
    print("\n=== record of call 1: resume =", r, "| steps_by_id size", len(v.get("steps_by_id", "")))
    if not r:
        print("no checkpoint in the record"); return
    tid = r.get("in_link") or r["tutorial_id"]
    if r["risk"] == "drops":
        note = (f"Last call ended on purpose at step {r['step']} ({r['heading']}) of tutorial_id {tid}. Ask whether "
                f"that step fixed the problem. If not, call next_step to continue.")
    else:
        note = (f"Last call dropped during step {r['step']} ({r['heading']}) of tutorial_id {tid}. Ask whether they "
                f"finished that step. If yes, call next_step. If not, call next_step with action repeat.")
    sid2 = s.create_session_id()
    print("=== call 2", sid2, "| note:", note)
    for i, text in enumerate(CALL2):
        turn(s, sid2, text, {"device": "iphone-13", "callback_note": note, "walk": v["walk"],
                             "steps_by_id": v["steps_by_id"]} if i == 0 else None)
    print("\n=== walk after call 2:", saved_state(sid2).get("walk"))


if __name__ == "__main__":
    {"install": install, "run": run}[sys.argv[1]]()
