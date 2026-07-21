import json

from backend import callbacks


class StubCtx:
    def __init__(self):
        self.state = {}


class _Tool:
    def __init__(self, name):
        self.name = name


def _mcp_response(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


def test_click_and_voice_select_line_produce_same_state():
    """A click (user_action injected as text) and speech both resolve to the
    same line_id, so the agent calls select_line(line_id) identically and the
    callback stages identical state."""
    resp = _mcp_response({"selected_line": "line_1243", "line_last4": "1243"})

    voice_ctx = StubCtx()
    callbacks.on_tool(_Tool("select_line"), {"line_id": "line_1243"}, voice_ctx, resp)

    click_ctx = StubCtx()
    callbacks.on_tool(_Tool("select_line"), {"line_id": "line_1243"}, click_ctx, resp)

    assert voice_ctx.state == click_ctx.state
    assert voice_ctx.state["selected_line"] == "line_1243"
