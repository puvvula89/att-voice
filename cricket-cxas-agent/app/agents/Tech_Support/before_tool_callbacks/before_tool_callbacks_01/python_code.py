"""before_tool_callback for Tech Support: fill save_progress with the caller's place from this call's
variables, so the model never copies the walk or the steps. next_step leaves the place to save in
walk["pending"]; marking walk["saved"] lets next_step release the step it was holding.

In chat, also fill sign_images with the picture names of the guide being walked (walk["active"]).

next_step gives one step per caller turn: once this turn has its step (`step_given`), a further
next_step call is answered here, without running the tool, so the model cannot look ahead and lose
the caller's place.

In chat the guide's link is never texted or typed by the model (the platform rejects a reply with
a web address in it): send_guide_link is answered here, and the title and url go to `show_link` for
the after_model_callback to show as a card under the reply.

When the concierge already fetched the saved place as the call connected (`resume_info`), get_progress
is answered here with that place: the server hands it out only once."""
import json
from typing import Any, Optional


def before_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext) -> Optional[dict[str, Any]]:
    if "get_progress" in (getattr(tool, "name", "") or "") and callback_context.variables.get("resume_info"):
        found = json.loads(callback_context.variables["resume_info"])
        callback_context.variables["resume_info"] = ""
        return {"progress": found}
    if "url" in input and "title" in input and callback_context.variables.get("channel") == "chat":
        callback_context.variables["show_link"] = json.dumps({"title": input["title"], "url": input["url"]})
        return {"shown": True, "note": "The link appears as a card under your reply. Say the link is just below; "
                                       "do not write the web address."}
    if "tutorial_id" in input and "walk" not in input and callback_context.variables.get("step_given"):
        return {"agent_action": "You already have this turn's step. Say that step to the caller now, "
                                "then wait for their reply before calling next_step again."}
    if "walk" in input and "steps_by_id" in input:
        walk = json.loads(callback_context.variables.get("walk") or "{}")
        save = walk.get("pending") or json.dumps({k: v for k, v in walk.items() if k != "saved"})
        input["walk"] = save
        input["steps_by_id"] = callback_context.variables.get("steps_by_id") or ""
        resume = json.loads(save).get("resume")
        if resume:
            walk["saved"] = json.dumps(resume, sort_keys=True)
            callback_context.variables["walk"] = json.dumps(walk)
    if "names" in input:
        walk = json.loads(callback_context.variables.get("walk") or "{}")
        tut = json.loads(callback_context.variables.get("steps_by_id") or "{}").get(walk.get("active", ""), {})
        names = [st["image"] for p in tut.get("paths", []) for st in p.get("steps", []) if st.get("image")]
        input["names"] = ",".join(dict.fromkeys(names))
    return None
