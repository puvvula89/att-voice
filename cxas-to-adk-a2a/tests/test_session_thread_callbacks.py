"""Prove the before/after tool session-threading callbacks against the SAME
datamodels + sandbox preamble CES uses."""
import cxas_scrapi.utils.callback_libs as clib
from session_thread_callbacks import (
    BEFORE_TOOL_CALLBACK_CODE,
    AFTER_TOOL_CALLBACK_CODE,
)

TOOL = "sales_adapter_call_sales_specialist"


def _load(code, fn):
    ns = {}
    exec("from cxas_scrapi.utils.callback_libs import *\n" + code, ns)
    return ns[fn]


def _tool(name=TOOL):
    return clib.Tool(name=name, description="d")


def _ctx(**state):
    return clib.CallbackContext(state=state)


# --- before_tool: inject cached session_id -----------------------------------

def test_before_injects_cached_session_id():
    cb = _load(BEFORE_TOOL_CALLBACK_CODE, "before_tool_callback")
    inp = {"customer_id": "wilson", "utterance": "upgrade"}
    out = cb(_tool(), inp, _ctx(adk_session_id="sess-123"))
    assert out is None                       # tool runs with mutated input
    assert inp["session_id"] == "sess-123"


def test_before_no_session_id_on_first_turn():
    cb = _load(BEFORE_TOOL_CALLBACK_CODE, "before_tool_callback")
    inp = {"customer_id": "wilson", "utterance": "upgrade"}
    cb(_tool(), inp, _ctx())                  # var unset
    assert "session_id" not in inp           # engine will resolve by user_id


def test_before_ignores_other_tools():
    cb = _load(BEFORE_TOOL_CALLBACK_CODE, "before_tool_callback")
    inp = {}
    cb(_tool("end_session"), inp, _ctx(adk_session_id="sess-123"))
    assert inp == {}


# --- after_tool: capture returned session_id ---------------------------------

def test_after_captures_session_id():
    cb = _load(AFTER_TOOL_CALLBACK_CODE, "after_tool_callback")
    ctx = _ctx()
    out = cb(_tool(), {"utterance": "x"}, ctx, {"response_text": "hi", "session_id": "sess-999"})
    assert out is None                       # response unchanged
    assert ctx.get_variable("adk_session_id") == "sess-999"


def test_after_no_id_in_response_is_noop():
    cb = _load(AFTER_TOOL_CALLBACK_CODE, "after_tool_callback")
    ctx = _ctx()
    cb(_tool(), {"utterance": "x"}, ctx, {"response_text": "hi"})
    assert ctx.get_variable("adk_session_id") is None


def test_after_ignores_other_tools():
    cb = _load(AFTER_TOOL_CALLBACK_CODE, "after_tool_callback")
    ctx = _ctx()
    cb(_tool("end_session"), {}, ctx, {"session_id": "sess-999"})
    assert ctx.get_variable("adk_session_id") is None


# --- round trip: after captures, before injects it next turn -----------------

def test_round_trip_capture_then_inject():
    after = _load(AFTER_TOOL_CALLBACK_CODE, "after_tool_callback")
    before = _load(BEFORE_TOOL_CALLBACK_CODE, "before_tool_callback")
    ctx = _ctx()
    after(_tool(), {"utterance": "turn1"}, ctx, {"session_id": "sess-abc"})
    inp = {"customer_id": "wilson", "utterance": "turn2"}
    before(_tool(), inp, ctx)
    assert inp["session_id"] == "sess-abc"
