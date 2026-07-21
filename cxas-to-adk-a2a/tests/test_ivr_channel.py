"""The before_model_callback that deterministically hides render_component on IVR
turns (message carries the [channel: ivr] marker) but leaves web-chat turns alone.
"""
from google.adk.models import LlmRequest
from google.adk.tools import FunctionTool
from google.genai import types

from backend import tools as bt
from backend.agent import hide_ui_for_ivr, IVR_MARKER


def _req(text):
    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(name="render_component"),
        types.FunctionDeclaration(name="get_lines"),
        types.FunctionDeclaration(name="end_call"),
    ])
    return LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=text)])],
        config=types.GenerateContentConfig(tools=[tool]),
        tools_dict={
            "render_component": FunctionTool(func=bt.render_component),
            "end_call": FunctionTool(func=bt.end_call),
        },
    )


def _names(req):
    return [f.name for t in (req.config.tools or []) for f in (t.function_declarations or [])]


def test_ivr_marker_hides_render_component():
    req = _req(f"upgrade my iphone {IVR_MARKER}")
    assert hide_ui_for_ivr(None, req) is None          # proceeds to the model
    names = _names(req)
    assert "render_component" not in names              # hidden from the model
    assert "get_lines" in names and "end_call" in names  # data/session tools kept
    assert "render_component" not in req.tools_dict


def test_no_marker_keeps_render_component():
    req = _req("upgrade my iphone")                     # web chat — no marker
    assert hide_ui_for_ivr(None, req) is None
    assert "render_component" in _names(req)
    assert "render_component" in req.tools_dict
