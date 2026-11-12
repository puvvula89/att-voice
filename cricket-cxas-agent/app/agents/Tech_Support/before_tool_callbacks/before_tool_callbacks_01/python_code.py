"""before_tool_callback for Tech Support: fill save_progress with the caller's place from this call's
variables, so the model never copies the walk or the steps. next_step leaves the place to save in
walk["pending"]; marking walk["saved"] lets next_step release the step it was holding.

In chat, also fill sign_images with the picture names of the guide being walked (walk["active"])."""
import json
from typing import Any, Optional


def before_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext) -> Optional[dict[str, Any]]:
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
