from backend import tools, stage_intents as si

class StubCtx:
    def __init__(self):
        self.state = {}

def test_get_lines_writes_state_and_returns_summary():
    ctx = StubCtx()
    result = tools.get_lines(tool_context=ctx)
    assert si.data_key(si.LINE_SELECTOR) in ctx.state
    assert ctx.state[si.data_key(si.LINE_SELECTOR)]["lines"][0]["last4"] == "1243"
    assert len(result["lines"]) == 3
    assert result["lines"][0]["line_id"] == "line_1243"

def test_get_eligible_phones_writes_state():
    ctx = StubCtx()
    result = tools.get_eligible_phones(line_id="line_1243", tool_context=ctx)
    staged = ctx.state[si.data_key(si.PHONE_OPTIONS)]
    assert staged["phones"][0]["phone_id"] == "iphone_17"
    assert staged["line_last4"] == "1243"          # context for the message token
    assert len(result["phones"]) == 3
    assert result["phones"][0]["phone_id"] == "iphone_17"

def test_select_line_records_choice():
    ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=ctx)
    assert ctx.state["selected_line"] == "line_1243"

def test_render_component_is_thin():
    ctx = StubCtx()
    result = tools.render_component(stage_intent=si.PHONE_OPTIONS, tool_context=ctx)
    assert result == {"status": "requested", "stage_intent": si.PHONE_OPTIONS}

from backend import callbacks

class _Tool:
    def __init__(self, name): self.name = name

def test_on_render_stashes_payload_and_acks():
    ctx = StubCtx()
    ctx.state[si.data_key(si.PHONE_OPTIONS)] = {
        "line_last4": "1243", "phones": [{"phone_id": "iphone_17", "name": "iPhone 17"}]}
    out = callbacks.on_render(
        tool=_Tool("render_component"),
        args={"stage_intent": si.PHONE_OPTIONS},
        tool_context=ctx,
        tool_response={"status": "requested", "stage_intent": si.PHONE_OPTIONS},
    )
    assert ctx.state["pending_ui"]["stage_intent"] == si.PHONE_OPTIONS
    assert ctx.state["pending_ui"]["options"][0]["submitValue"] == "iphone_17"
    assert out == {"status": "shown"}

def test_on_render_passthrough_for_other_tools():
    ctx = StubCtx()
    out = callbacks.on_render(
        tool=_Tool("get_lines"), args={}, tool_context=ctx,
        tool_response={"count": 3},
    )
    assert out is None

def test_select_phone_stages_confirmation():
    ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=ctx)
    result = tools.select_phone(phone_id="iphone_17", tool_context=ctx)
    assert result == {"selected_phone": "iphone_17"}
    conf = ctx.state[si.data_key(si.CONFIRMATION)]
    assert conf["line_last4"] == "1243"            # resolved to display digits
    assert conf["phone"] == "iPhone 17"            # resolved to display name
    assert conf["monthly_price"] == 32.99
    assert conf["terms"] == "24-month installment"

def test_confirm_upgrade_stages_receipt():
    ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=ctx)
    tools.select_phone(phone_id="iphone_17", tool_context=ctx)
    result = tools.confirm_upgrade(tool_context=ctx)
    assert result == {"order_id": "UPG-100423"}
    receipt = ctx.state[si.data_key(si.RECEIPT)]
    assert receipt["order_id"] == "UPG-100423"
    assert receipt["phone"] == "iPhone 17"          # resolved to display name
    assert receipt["ship_estimate"] == "3-5 business days"
