from backend import formatter

def on_render(tool, args, tool_context, tool_response):
    """after_tool_callback: turn a render_component call into a UI payload in state."""
    if tool.name == "render_component":
        payload = formatter.build_payload(args["stage_intent"], tool_context.state)
        tool_context.state["pending_ui"] = payload   # relay reads this from state_delta
        return {"status": "shown"}                    # model sees an ack, never narrates JSON
    return None
