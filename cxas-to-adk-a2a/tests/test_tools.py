import json

from backend import tools, callbacks, stage_intents as si


class StubCtx:
    def __init__(self):
        self.state = {}


class _Tool:
    def __init__(self, name):
        self.name = name


def _mcp_response(data: dict) -> dict:
    """Shape ADK hands the callback for a remote MCP tool (CallToolResult)."""
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


# --- agent-local tools -------------------------------------------------------

def test_render_component_is_thin():
    ctx = StubCtx()
    result = tools.render_component(stage_intent=si.PHONE_OPTIONS, tool_context=ctx)
    assert result == {"status": "requested", "stage_intent": si.PHONE_OPTIONS}


def test_end_call_is_thin():
    assert tools.end_call(tool_context=StubCtx()) == {"status": "ending"}


# --- callback: render / end_call side-effects --------------------------------

def test_on_tool_render_stashes_payload_and_acks():
    ctx = StubCtx()
    ctx.state[si.data_key(si.PHONE_OPTIONS)] = {
        "line_last4": "1243", "phones": [{"phone_id": "iphone_17", "name": "iPhone 17"}]}
    out = callbacks.on_tool(
        tool=_Tool("render_component"),
        args={"stage_intent": si.PHONE_OPTIONS},
        tool_context=ctx,
        tool_response={"status": "requested", "stage_intent": si.PHONE_OPTIONS},
    )
    assert ctx.state["pending_ui"]["stage_intent"] == si.PHONE_OPTIONS
    assert ctx.state["pending_ui"]["options"][0]["submitValue"] == "iphone_17"
    assert out == {"status": "shown"}


def test_on_tool_end_call_marks_state():
    ctx = StubCtx()
    out = callbacks.on_tool(_Tool("end_call"), {}, ctx, {"status": "ending"})
    assert ctx.state["call_ended"] is True
    assert out == {"status": "ended"}


# --- callback: staging MCP data-tool responses into state --------------------

def test_on_tool_stages_get_lines():
    ctx = StubCtx()
    callbacks.on_tool(
        _Tool("get_lines"), {}, ctx,
        _mcp_response({"lines": [{"line_id": "line_1243", "last4": "1243", "device": "iPhone 12"}]}),
    )
    staged = ctx.state[si.data_key(si.LINE_SELECTOR)]
    assert staged["lines"][0]["last4"] == "1243"


def test_on_tool_stages_eligible_phones():
    ctx = StubCtx()
    callbacks.on_tool(
        _Tool("get_eligible_phones"), {"line_id": "line_1243"}, ctx,
        _mcp_response({"line_last4": "1243", "phones": [{"phone_id": "iphone_17"}]}),
    )
    staged = ctx.state[si.data_key(si.PHONE_OPTIONS)]
    assert staged["line_last4"] == "1243"
    assert staged["phones"][0]["phone_id"] == "iphone_17"


def test_on_tool_stages_select_line():
    ctx = StubCtx()
    callbacks.on_tool(
        _Tool("select_line"), {"line_id": "line_1243"}, ctx,
        _mcp_response({"selected_line": "line_1243", "line_last4": "1243"}),
    )
    assert ctx.state["selected_line"] == "line_1243"


def test_on_tool_stages_select_phone_confirmation():
    ctx = StubCtx()
    callbacks.on_tool(
        _Tool("select_phone"), {"line_id": "line_1243", "phone_id": "iphone_17"}, ctx,
        _mcp_response({
            "selected_phone": "iphone_17", "selected_phone_name": "iPhone 17",
            "confirmation": {"line_last4": "1243", "phone": "iPhone 17",
                             "monthly_price": 32.99, "terms": "24-month installment"}}),
    )
    assert ctx.state["selected_phone"] == "iphone_17"
    assert ctx.state["selected_phone_name"] == "iPhone 17"
    conf = ctx.state[si.data_key(si.CONFIRMATION)]
    assert conf["phone"] == "iPhone 17"
    assert conf["monthly_price"] == 32.99


def test_on_tool_stages_confirm_upgrade_receipt():
    ctx = StubCtx()
    callbacks.on_tool(
        _Tool("confirm_upgrade"), {"line_id": "line_1243", "phone_id": "iphone_17"}, ctx,
        _mcp_response({"order_id": "UPG-100423", "receipt": {
            "order_id": "UPG-100423", "phone": "iPhone 17", "ship_estimate": "3-5 business days"}}),
    )
    receipt = ctx.state[si.data_key(si.RECEIPT)]
    assert receipt["order_id"] == "UPG-100423"
    assert receipt["phone"] == "iPhone 17"


def test_unwrap_handles_plain_dict_and_structured_content():
    # plain dict (local FunctionTool style)
    assert callbacks._unwrap({"selected_line": "x"}) == {"selected_line": "x"}
    # structuredContent path (if a future typed MCP tool populates it)
    assert callbacks._unwrap(
        {"structuredContent": {"a": 1}, "content": []}) == {"a": 1}
