"""before_agent_callback: copy this turn's modality into `channel` ("voice" or "chat"), so the
instruction and the other callbacks can tell a phone call from a web chat. One app serves both.
Also clear `step_given`, which limits next_step to one step per caller turn."""
from typing import Optional


def before_agent_callback(callback_context: CallbackContext) -> Optional[Content]:
    session = callback_context.variables.get("_session") or {}
    callback_context.variables["channel"] = "chat" if session.get("modality") == "TEXT" else "voice"
    callback_context.variables["step_given"] = ""
    return None
