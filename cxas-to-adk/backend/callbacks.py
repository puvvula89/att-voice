"""after_tool_callback: stage tool results into session state for the UI.

Two kinds of tools flow through here:

- **Agent-local FunctionTools** (``render_component``, ``end_call``) — UI /
  session-control side-effects. Their response reaches us as a plain dict.
- **Remote MCP data tools** (``get_lines`` … ``confirm_upgrade``) — the data
  lives in the MCP server, so ADK hands us a CallToolResult-shaped dict
  (``{"content": [{"type":"text","text":"<json>"}], ...}``). We unwrap it and
  stage the payload under the ``data:<stage_intent>`` keys the formatter reads.
"""
import json

from backend import formatter, stage_intents as si


def _unwrap(tool_response):
    """Return the tool's data dict whether it came from a local FunctionTool
    (plain dict) or a remote MCP tool (CallToolResult dict)."""
    if isinstance(tool_response, dict) and (
        "content" in tool_response or "structuredContent" in tool_response
    ):
        structured = tool_response.get("structuredContent")
        if isinstance(structured, dict):
            # FastMCP nests scalar/non-object returns under "result"; ours are
            # objects, but unwrap defensively.
            return structured.get("result", structured)
        for item in tool_response.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (ValueError, KeyError):
                    continue
        return {}
    return tool_response if isinstance(tool_response, dict) else {}


def on_tool(tool, args, tool_context, tool_response):
    name = tool.name
    state = tool_context.state

    # --- agent-local UI / session-control tools -----------------------------
    if name == "render_component":
        payload = formatter.build_payload(args["stage_intent"], state)
        state["pending_ui"] = payload   # relay reads this from state_delta
        return {"status": "shown"}      # model sees an ack, never narrates JSON
    if name == "end_call":
        state["call_ended"] = True      # relay reads this from state_delta → closes
        return {"status": "ended"}

    # --- remote MCP data tools: stage their payload for the formatter -------
    data = _unwrap(tool_response)
    if name == "get_lines":
        state[si.data_key(si.LINE_SELECTOR)] = {"lines": data.get("lines", [])}
    elif name == "get_eligible_phones":
        state[si.data_key(si.PHONE_OPTIONS)] = {
            "line_last4": data.get("line_last4", ""),
            "phones": data.get("phones", []),
        }
    elif name == "select_line":
        if "selected_line" in data:
            state["selected_line"] = data["selected_line"]
    elif name == "select_phone":
        if "selected_phone" in data:
            state["selected_phone"] = data["selected_phone"]
        if "selected_phone_name" in data:
            state["selected_phone_name"] = data["selected_phone_name"]
        if "confirmation" in data:
            state[si.data_key(si.CONFIRMATION)] = data["confirmation"]
    elif name == "confirm_upgrade":
        if "receipt" in data:
            state[si.data_key(si.RECEIPT)] = data["receipt"]
    return None


# Backwards-compatible alias (the callback now covers all tools, not just render).
on_render = on_tool
