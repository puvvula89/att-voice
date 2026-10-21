"""next_step: the agent's step tool. Runs inside the agent platform (stdlib only, no network).

Reads the tutorials the search callback saved in `steps_by_id`, returns one step per call, and keeps the
caller's place in the session variable `walk`. A step that ends the call is withheld until the caller was
warned on an earlier call and said yes. A step that ends or might drop the call is also withheld until its
place is saved on the server (save_first), so a callback resumes at that exact step.

next_step must stay the first function: the platform takes the first one in the file as the tool.
"""
import json

SAY_CALL_ENDING = ("This next step will disconnect our call. I'll save your place so we can pick up right after "
                   "it when you call back. Please confirm by saying you're okay to call back.")
REASK = "I need your confirmation before we run this step. Are you okay to call back?"


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
        return {"agent_action": "That tutorial is not loaded. Search for it by its title, then call next_step again."}
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
            return {"agent_action": "Not a valid choice. Ask again with one of choices.", "choices": _forks(paths)}
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
        return {"needs_choice": True, "question": steps[-1]["text"].split("\n")[-1], "choices": _forks(paths)}
    if n > len(steps):
        back = walk.get("stack", [])
        walk["active"] = back.pop() if back else ""
        set_variable("walk", json.dumps(walk))
        if walk["active"]:
            return {"finished": True, "return_to": walk["active"],
                    "say": "That finishes this part. Call next_step with return_to to continue the main guide."}
        return {"finished": True, "say": "That was the last step. Ask if the problem is fixed."}
    s = steps[n - 1]
    resume = None
    if action != "repeat":   # where a dropped call resumes
        root = (walk.get("stack") or [tutorial_id])[0]
        risk = "drops" if s["call_ending"] else ("may_drop" if s.get("may_drop") else "safe")
        resume = {"tutorial_id": root, "step": n if root == tutorial_id else prog[root]["done"],
                  "heading": s["heading"] or s["text"].split("\n")[0][:80], "risk": risk,
                  "choice": prog[root]["choice"]}
        if root != tutorial_id:
            resume["in_link"] = tutorial_id
    if resume and resume["risk"] != "safe":
        gate = {}
        if s["call_ending"] and not p.get("covered") and (p.get("warned") != n or not caller_confirmed):
            p["warned"] = n
            gate = {"needs_confirmation": True, "say_first": SAY_CALL_ENDING, "if_unclear": REASK}
        if walk.get("saved") != json.dumps(resume, sort_keys=True):
            # Withheld until the place is saved on the server, as if this step were done; the agent's
            # save_progress callback sends `pending` and records `saved`.
            after = json.loads(json.dumps({k: v for k, v in walk.items() if k not in ("pending", "saved")}))
            after["progress"][tutorial_id]["done"] = n
            after["resume"] = resume
            walk["pending"] = json.dumps(after)
            gate["save_first"] = True
        if gate:
            set_variable("walk", json.dumps(walk))
            return {"step": n, "of": len(steps), **gate}
    if resume:
        walk["resume"] = resume
    walk.pop("pending", None)
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
