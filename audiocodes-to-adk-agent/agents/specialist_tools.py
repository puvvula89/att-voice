from __future__ import annotations

from agents.intent_tool import classify_intent, on_intent
from agents.end_call_tool import end_call, on_end_call

# Specialists carry BOTH tools: classify_intent (to re-route if they're the wrong
# specialist) and end_call (to hang up after the closing line). One after_tool_callback
# dispatches both — each underlying handler is a no-op unless its tool fired.

__all__ = ["classify_intent", "end_call", "on_specialist_tool"]


def on_specialist_tool(tool, args, tool_context, tool_response):
    on_intent(tool, args, tool_context, tool_response)
    on_end_call(tool, args, tool_context, tool_response)
    return None
