from __future__ import annotations


def end_call() -> dict:
    """End the call. Call this AFTER you have spoken the closing line, once the
    caller has confirmed they need nothing else.
    """
    return {"status": "ended"}


def on_end_call(tool, args, tool_context, tool_response):
    """after_tool_callback: stage the end signal into session state for the relay.

    The relay reads it from the run_live event's actions.state_delta.end_call and
    tears the call down (yields AgentEnd).
    """
    if tool.name == "end_call":
        tool_context.state["end_call"] = True
    return None
