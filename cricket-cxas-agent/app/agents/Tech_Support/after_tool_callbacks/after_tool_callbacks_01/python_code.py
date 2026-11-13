"""after_tool_callback for Tech Support. Runs for every tool, so it acts only on these results:

- search_tutorials: keep only tutorials for the caller's phone (the device in the search filter), save
  their steps in `steps_by_id` for next_step, and show the model titles and summaries without the steps.
- get_progress: move the saved `walk` and `steps_by_id` into this call's variables, so next_step
  continues from the saved place, and show the model only where the caller left off.
- next_step: take the step's picture name off the result. In chat (`channel` is "chat") it goes to
  `show_image` for the after_model_callback to attach, and the model is told whether there is a picture
  and, the first time a guide's pictures are needed, to get their links; on voice it is dropped.
- sign_images (chat only): keep the signed links in `image_links`, by picture name.
"""
import base64
import json
import re
import zlib
from typing import Any, Optional


def _payload(tool_response: dict) -> dict:
    """An MCP result arrives as {"text_output": [result]}; also accept the dict itself, result or
    structuredContent wrappers, and JSON text content."""
    r = tool_response
    if isinstance(r.get("text_output"), list) and r["text_output"] and isinstance(r["text_output"][0], dict):
        return r["text_output"][0]
    for key in ("result", "structuredContent"):
        if isinstance(r, dict) and isinstance(r.get(key), dict):
            r = r[key]
    if isinstance(r, dict) and isinstance(r.get("content"), list):
        for part in r["content"]:
            try:
                return json.loads(part.get("text", ""))
            except (ValueError, AttributeError):
                continue
    return r if isinstance(r, dict) else {}


def _search(input: dict, callback_context: CallbackContext, answer: str) -> dict:
    m = re.search(r'device:\s*ANY\("([^"]+)"\)', str(input.get("filter", "")))
    device = m.group(1) if m else ""
    if not device:
        return {"answer": "Search again with the filter set to the caller's phone, exactly: device: ANY(\"<device>\")."}
    steps_by_id = json.loads(callback_context.variables.get("steps_by_id") or "{}")
    kept = []
    for b in (x.strip() for x in re.split(r"\n\s*\n", answer)):
        dev = re.search(r"^device: ?(\S+)", b, re.M)
        tid = re.search(r"^tutorial_id: ?(\S+)", b, re.M)
        if not b.startswith("[") or not (dev and tid) or dev.group(1) != device:
            continue
        title = re.sub(r"^\[\d+\] ?", "", b.split("\n", 1)[0]).strip()
        enc = re.search(r"^steps_b64: ?([A-Za-z0-9_=-]+)", b, re.M)
        if enc:
            steps = json.loads(zlib.decompress(base64.urlsafe_b64decode(enc.group(1))).decode())
            steps_by_id[tid.group(1)] = {"title": title, **steps}
        body = re.sub(r"^\[\d+\] ?", "", re.sub(r"^steps_b64:.*\n?", "", b, flags=re.M))
        kept.append("[" + str(len(kept) + 1) + "] " + body)
    callback_context.variables["steps_by_id"] = json.dumps(steps_by_id, ensure_ascii=False)
    if not kept:
        return {"answer": "No tutorial matched this phone. Ask the caller to describe the problem another way."}
    return {"answer": "\n\n".join(kept)}


def after_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext,
                        tool_response: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "answer" in tool_response:
        return _search(input, callback_context, str(tool_response["answer"]))
    # A python tool's result arrives wrapped as {"result": {...}}; edit it in place and return the whole.
    step = tool_response.get("result") if isinstance(tool_response.get("result"), dict) else tool_response
    if "step" in step and "of" in step:
        image = step.pop("image", "")
        if "text" in step:
            callback_context.variables["step_given"] = "1"   # one step per caller turn; see before_tool
        if callback_context.variables.get("channel") != "chat" or "text" not in step:
            return tool_response if image else None   # voice, or a save/confirm result with no step to show
        # "-" marks a step without a picture: the reply still gets quick replies.
        callback_context.variables["show_image"] = image or "-"
        step["picture"] = bool(image)
        if image and image not in json.loads(callback_context.variables.get("image_links") or "{}"):
            step["get_pictures"] = True
        return tool_response
    r = _payload(tool_response)
    if isinstance(r.get("images"), dict):
        links = json.loads(callback_context.variables.get("image_links") or "{}")
        links.update(r["images"])
        callback_context.variables["image_links"] = json.dumps(links)
        return {"images_ready": len(r["images"])}
    if "progress" in r and r.get("walk"):
        callback_context.variables["walk"] = r["walk"]
        callback_context.variables["steps_by_id"] = r.get("steps_by_id") or "{}"
        return {"progress": r["progress"]}
    return None
