"""after_tool_callback for the concierge. Its one support tool is get_progress, called when a phone
call connects. The server hands a saved place out once, so keep it for the specialist: `walk` and
`steps_by_id` go into this call's variables, as Tech Support's own callback would do, and the place
itself goes into `resume_info`, which Tech Support's before_tool_callback returns when the specialist
asks for the saved place. The model sees only where the caller left off."""
import json
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


def after_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext,
                        tool_response: dict[str, Any]) -> Optional[dict[str, Any]]:
    r = _payload(tool_response)
    if not (r.get("progress") and r.get("walk")):
        return None
    callback_context.variables["walk"] = r["walk"]
    callback_context.variables["steps_by_id"] = r.get("steps_by_id") or "{}"
    callback_context.variables["resume_info"] = json.dumps(r["progress"])
    return {"progress": r["progress"]}
