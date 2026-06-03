from backend import tools, stage_intents as si

class StubCtx:
    def __init__(self):
        self.state = {}

def test_get_lines_writes_state_and_returns_summary():
    ctx = StubCtx()
    result = tools.get_lines(tool_context=ctx)
    assert si.data_key(si.LINE_SELECTOR) in ctx.state
    assert ctx.state[si.data_key(si.LINE_SELECTOR)]["lines"][0]["last4"] == "1243"
    assert result["count"] == 3

def test_get_eligible_phones_writes_state():
    ctx = StubCtx()
    result = tools.get_eligible_phones(line_id="line_1243", tool_context=ctx)
    assert ctx.state[si.data_key(si.PHONE_OPTIONS)]["phones"][0]["phone_id"] == "iphone_17"
    assert result["count"] == 3

def test_select_line_records_choice():
    ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=ctx)
    assert ctx.state["selected_line"] == "line_1243"

def test_render_component_is_thin():
    ctx = StubCtx()
    result = tools.render_component(stage_intent=si.PHONE_OPTIONS, tool_context=ctx)
    assert result == {"status": "requested", "stage_intent": si.PHONE_OPTIONS}
