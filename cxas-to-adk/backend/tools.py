"""Agent-local tools.

Only UI / session-control tools live here. They depend on ADK
``tool_context.state`` (read by the relay from ``state_delta``), so they cannot
move to the remote MCP server. The data tools (get_lines, get_eligible_phones,
select_line, select_phone, confirm_upgrade) are served by ``mcp_server`` and
consumed via ``McpToolset``; their results are staged by ``backend.callbacks``.
"""


def render_component(stage_intent: str, tool_context) -> dict:
    """Render the named UI component. Choose stage_intent based on the user's request.
    Valid values: line_selector, phone_options, confirmation, receipt."""
    return {"status": "requested", "stage_intent": stage_intent}


def end_call(tool_context) -> dict:
    """End the session after the customer confirms they need nothing else. Call this
    only after saying the closing line aloud."""
    return {"status": "ending"}
