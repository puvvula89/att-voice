from backend import tools, stage_intents as si

class StubCtx:
    def __init__(self, state=None): self.state = state or {}

def test_click_and_voice_select_line_produce_same_state():
    # "voice": agent calls select_line after understanding speech
    voice_ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=voice_ctx)

    # "click": user_action -> injected turn -> agent calls select_line with same id
    click_ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=click_ctx)

    assert voice_ctx.state == click_ctx.state
    assert voice_ctx.state["selected_line"] == "line_1243"
