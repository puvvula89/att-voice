"""Spike: in-platform python next_step walks the tutorial the search callback saved.

next_step reads `steps_by_id` (written by the guard callback), returns one step per call, keeps the
checkpoint in the session variable `walk`, and withholds a call-ending step's text until the caller
has been warned on an earlier call and has confirmed.

  install <env>   add next_step to spike-dstool and switch the instruction to a walk
  run <env>       scripted caller; prints each turn, the tool calls, and `walk` after each turn
"""
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(sys.argv[2])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
APP = f"projects/{PROJECT}/locations/us/apps/spike-dstool"

NEXT_STEP = '''
import json

SAY_CALL_ENDING = ("This next step will disconnect our call. I'll save your place so we can pick up right after "
                   "it when you call back. Please confirm by saying you're okay to call back.")
REASK = "I need your confirmation before we run this step. Are you okay to call back?"


def _shared(paths: list) -> list:
    out = []
    for group in zip(*(p["steps"] for p in paths)):
        if len({s["text"] for s in group}) > 1:
            break
        out.append(group[0])
    return out


def _forks(paths: list) -> list:
    common = set.intersection(*(set(p["choices"]) for p in paths))
    return sorted({c for p in paths for c in p["choices"]} - common)


def next_step(tutorial_id: str, action: str = "next", caller_confirmed: bool = False, choice: str = "") -> dict:
    """Give the caller the next step of the confirmed tutorial, one step per call.

    Args:
        tutorial_id: id of the tutorial the caller confirmed (or of a linked tutorial you just searched for).
        action: "next" for the next step (the first call returns step 1), or "repeat" for the current step again.
        caller_confirmed: true only after the caller said yes to the disconnect warning for this step.
        choice: when next_step returned needs_choice, the option the caller picked, copied exactly.
    """
    tut = json.loads(get_variable("steps_by_id") or "{}").get(tutorial_id)
    if not tut:
        return {"error": "That tutorial is not loaded. Search for it by its title, then call next_step again."}
    walk = json.loads(get_variable("walk") or "{}")
    prog = walk.setdefault("progress", {})
    active = walk.get("active")
    stack = walk.setdefault("stack", [])
    if tutorial_id in stack:   # went back to a guide we were inside: drop it and anything above it
        del stack[stack.index(tutorial_id):]
    entering = active and active != tutorial_id and tutorial_id not in prog
    if entering:
        walk.setdefault("stack", []).append(active)   # following a link; come back here after
    walk["active"] = tutorial_id
    p = prog.setdefault(tutorial_id, {"done": 0, "warned": 0, "choice": ""})
    if entering:
        parent = prog[active]
        # the link explains a call-ending step the caller already agreed to: don't warn twice
        p["covered"] = bool(parent["done"] and parent["warned"] == parent["done"])
    paths = tut["paths"]
    if choice and len(paths) > 1:
        if choice not in _forks(paths):
            return {"error": "Not a valid choice.", "choices": _forks(paths)}
        p["choice"] = choice
    if len(paths) == 1:
        steps = paths[0]["steps"]
    elif p["choice"]:
        steps = next(x["steps"] for x in paths if p["choice"] in x["choices"])
    else:
        steps = _shared(paths)
    n = p["done"] if action == "repeat" and p["done"] else p["done"] + 1
    if n > len(steps) and len(paths) > 1 and not p["choice"]:
        set_variable("walk", json.dumps(walk))
        return {"needs_choice": True, "question": steps[-1]["text"].split("\\n")[-1], "choices": _forks(paths)}
    if n > len(steps):
        back = walk.get("stack", [])
        walk["active"] = back.pop() if back else ""
        set_variable("walk", json.dumps(walk))
        if walk["active"]:
            return {"finished": True, "return_to": walk["active"],
                    "say": "That finishes this part. Call next_step with return_to to continue the main guide."}
        return {"finished": True, "say": "That was the last step. Ask if the problem is fixed."}
    s = steps[n - 1]
    if s["call_ending"] and action != "repeat":
        if not p.get("covered") and (p.get("warned") != n or not caller_confirmed):
            p["warned"] = n
            set_variable("walk", json.dumps(walk))
            return {"step": n, "of": len(steps), "needs_confirmation": True, "say_first": SAY_CALL_ENDING,
                    "if_unclear": REASK}
    if action != "repeat":   # checkpoint every step; a dropped call resumes here
        root = (walk.get("stack") or [tutorial_id])[0]
        risk = "drops" if s["call_ending"] else ("may_drop" if s.get("may_drop") else "safe")
        walk["resume"] = {"tutorial_id": root, "step": n if root == tutorial_id else prog[root]["done"],
                          "heading": s["heading"] or s["text"].split("\\n")[0][:80], "risk": risk,
                          "choice": prog[root]["choice"]}
        if root != tutorial_id:
            walk["resume"]["in_link"] = tutorial_id
    p["done"] = n
    set_variable("walk", json.dumps(walk))
    out = {"step": n, "of": len(steps), "heading": s["heading"], "text": s["text"], "call_ending": s["call_ending"]}
    for k in ("notes", "substeps", "how_to"):
        if s.get(k):
            out[k] = s[k]
    if s.get("warning"):
        out["warning"] = s["warning"]
    extra = [o for o in s.get("options", []) if not o.startswith("Next")]
    if extra:
        out["options"] = extra
    return out
'''

INSTRUCTION = """The caller's phone is {device}.
1. When the caller describes a problem, call search_tutorials once with their problem and set filter to exactly:
   device: ANY("{device}"). Name the best matching title and, in the same question, offer: "I can text you the
   guide, walk you through it now, or both." If two titles fit equally, ask one either-or question first.
2. When they pick walking through it (or both), call next_step with that tutorial_id and read the step to them
   in plain words. Then wait. If they say it's not their problem, ask them to describe it again.
3. Each time they say they did it, call next_step again. If they ask to hear it again, call next_step with
   action "repeat".
4. If next_step returns needs_confirmation, say the say_first text and wait. Only a clear yes to calling back
   counts ("yes", "I'm okay to call back"). Anything else ("done", "ok?", a question, silence) is not a yes:
   say the if_unclear text and wait again. After a clear yes, call next_step with caller_confirmed true.
5. If next_step returns needs_choice, ask its question with the choices, then call next_step with the
   caller's pick as choice.
6. If a step has how_to and the caller doesn't know how to do it, read the how_to steps one at a time.
7. Read only what next_step returns. Never invent steps. If a tool fails, say you can text the guide link instead."""


def install():
    import google.cloud.ces_v1beta.types as T
    from cxas_scrapi.core.tools import Tools
    from google.cloud import ces_v1beta
    from google.protobuf import field_mask_pb2
    try:
        Tools(app_name=APP).create_tool(tool_id="next-step", display_name="next_step",
                                        payload={"python_code": NEXT_STEP},
                                        description="Give the caller the next step of the confirmed tutorial.")
        print("tool created")
    except Exception as e:  # noqa: BLE001
        print("tool:", type(e).__name__, str(e)[:200])
        c = ces_v1beta.AgentServiceClient()
        t = c.get_tool(name=f"{APP}/tools/next-step")
        t.python_function.python_code = NEXT_STEP
        c.update_tool(tool=t, update_mask=field_mask_pb2.FieldMask(paths=["python_function.python_code"]))
        print("tool updated")
    c = ces_v1beta.AgentServiceClient()
    a = c.get_agent(name=f"{APP}/agents/spike")
    a.instruction = INSTRUCTION
    a.tools[:] = [f"{APP}/tools/search-tutorials", f"{APP}/tools/next-step"]
    c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["instruction", "tools"]))
    print("agent updated")


CALLER = ["my wifi is really slow", "walk me through it", "ok", "done, I see the checkmark", "done",
          "done", "yes I'm okay to call back, but how do I restart it?", "ok"]


def run():
    from cxas_scrapi.core.sessions import Sessions
    from google.protobuf.json_format import MessageToDict
    s = Sessions(app_name=APP)
    sid = s.create_session_id()
    walk = ""
    for i, text in enumerate(CALLER):
        res = None
        for k in range(10):
            try:
                res = MessageToDict(s.run(sid, text=text, variables={"device": "iphone-13"} if i == 0 else None)._pb)
                break
            except Exception as e:  # noqa: BLE001
                print("   (retry", str(e)[:40] + ")", flush=True); time.sleep(30)
        print(f"\n> {text}")
        for o in res.get("outputs", []):
            for m in o.get("diagnosticInfo", {}).get("messages", []):
                for c in m.get("chunks", []):
                    if "toolCall" in c and c["toolCall"].get("displayName") == "next_step":
                        print("   [next_step]", json.dumps(c["toolCall"].get("args")))
                    elif "toolCall" in c:
                        print("   [search]", json.dumps(c["toolCall"].get("args"))[:120])
                    if "toolResponse" in c and "next-step" in c["toolResponse"].get("tool", ""):
                        r = dict(c["toolResponse"].get("response", {}))
                        if "text" in r:
                            r["text"] = r["text"][:70] + "…"
                        print("   [returned]", json.dumps(r)[:240])
                    walk = (c.get("updatedVariables") or {}).get("walk", walk)
            if o.get("text"):
                print("  agent:", o["text"].replace("\n", " ")[:260])
        print("   walk =", walk, flush=True)
        time.sleep(20)


if __name__ == "__main__":
    {"install": install, "run": run}[sys.argv[1]]()
