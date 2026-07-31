"""Prove the hydration before_model callback against the SAME datamodels and
sandbox preamble CES uses.

We exec BEFORE_MODEL_CALLBACK_CODE with the callback_libs wildcard import
prepended (exactly what CES injects), then drive it with constructed
CallbackContext / LlmRequest objects. Nothing is mocked — these are the real
pydantic models the sandbox hands the callback.

The contract under test:
  * fires exactly once, on the first model step,
  * only when `customer_id` is non-empty,
  * never again afterwards, on any later turn,
  * and hides the tool from the model whenever hydration is settled.
"""
import os
import sys

import cxas_scrapi.utils.callback_libs as clib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "steering"))

from hydration_callback import BEFORE_MODEL_CALLBACK_CODE, TOOL


def _load_callback():
    ns = {}
    exec(
        "from cxas_scrapi.utils.callback_libs import *\n" + BEFORE_MODEL_CALLBACK_CODE,
        ns,
    )
    return ns["before_model_callback"]


def _ctx(state=None, events=None):
    return clib.CallbackContext(state=dict(state or {}), events=list(events or []))


def _request():
    """An LlmRequest carrying the tool in its schema, as the model would see it."""
    return clib.LlmRequest(
        model="gemini-3.1-flash-live",
        config=clib.GenerateContentConfig(
            tools=[
                clib.ToolDeclaration(
                    function_declarations=[clib.FunctionDeclaration(name=TOOL)]
                )
            ]
        ),
    )


def _event(part, author="model"):
    return clib.Event(
        id="e1",
        author=author,
        timestamp=0,
        invocationId="inv-1",
        content=clib.Content(role=author, parts=[part]),
    )


def _hidden(req):
    return TOOL in (req.config.excluded_tools or [])


def _injected_call(resp):
    """The FunctionCall the callback injected, or None."""
    if resp is None or resp.content is None:
        return None
    for p in resp.content.parts or []:
        if p.function_call is not None:
            return p.function_call
    return None


# --- the happy path: customer id present -> fire, exactly once ----------------

def test_fires_hydration_when_customer_id_present():
    cb = _load_callback()
    ctx = _ctx({"customer_id": "cust-a1b2", "resume_conversation_id": "conv-xyz"})
    req = _request()

    out = cb(ctx, req)

    call = _injected_call(out)
    assert call is not None, "expected the callback to inject the tool call"
    assert call.name == TOOL
    assert call.args["customer_id"] == "cust-a1b2"
    assert call.args["conversation_id"] == "conv-xyz"
    # The latch is set BEFORE firing, so a retried step cannot double-fire.
    assert ctx.get_variable("hydrated") == "done"


def test_second_model_step_returns_none_and_hides_the_tool():
    """After the tool result comes back, the model runs for real — tool gone."""
    cb = _load_callback()
    ctx = _ctx({"customer_id": "cust-a1b2", "hydrated": "done"})
    req = _request()

    assert cb(ctx, req) is None
    assert _hidden(req), "settled hydration must remove the tool from the schema"


def test_never_fires_again_on_later_turns():
    cb = _load_callback()
    ctx = _ctx({"customer_id": "cust-a1b2"})

    first = cb(ctx, _request())
    assert _injected_call(first) is not None

    # Turns 2..5 reuse the same session state — the latch persists.
    for _ in range(4):
        req = _request()
        assert cb(ctx, req) is None
        assert _hidden(req)


# --- the gate: no customer id -> never fire ----------------------------------

def test_does_not_fire_without_customer_id():
    cb = _load_callback()
    ctx = _ctx({"resume_conversation_id": "conv-xyz"})  # id present but no customer
    req = _request()

    assert cb(ctx, req) is None
    assert ctx.get_variable("hydrated") == "skipped"
    assert _hidden(req), "the model must not even see a tool it may not use"


def test_blank_customer_id_is_treated_as_absent():
    cb = _load_callback()
    ctx = _ctx({"customer_id": "   "})

    assert cb(ctx, _request()) is None
    assert ctx.get_variable("hydrated") == "skipped"


def test_skipped_conversation_stays_skipped():
    """A conversation that started without a customer id never hydrates later."""
    cb = _load_callback()
    ctx = _ctx({})
    cb(ctx, _request())

    # Even if a customer id shows up mid-conversation, the latch holds.
    ctx.set_variable("customer_id", "cust-late")
    req = _request()
    assert cb(ctx, req) is None
    assert _hidden(req)


# --- lock 2: turn-local replay, before the state delta has landed ------------

def test_does_not_refire_when_tool_already_called_this_turn():
    cb = _load_callback()
    prior = clib.Part.from_function_call(TOOL, {"customer_id": "cust-a1b2"})
    ctx = _ctx({"customer_id": "cust-a1b2"}, events=[_event(prior)])
    req = _request()

    assert cb(ctx, req) is None
    assert ctx.get_variable("hydrated") == "done"
    assert _hidden(req)


def test_does_not_refire_when_tool_response_already_present():
    cb = _load_callback()
    prior = clib.Part.from_function_response(TOOL, {"found": True, "topic": "internet"})
    ctx = _ctx({"customer_id": "cust-a1b2"}, events=[_event(prior)])

    assert cb(ctx, _request()) is None
    assert ctx.get_variable("hydrated") == "done"


# --- robustness: the sandbox may hand us a request without a config ----------

def test_survives_missing_request_config():
    cb = _load_callback()
    ctx = _ctx({})
    req = clib.LlmRequest(model="gemini-3.1-flash-live", config=None)

    assert cb(ctx, req) is None  # must not raise
    assert ctx.get_variable("hydrated") == "skipped"


def test_missing_resume_id_sends_empty_string():
    """customer_id gates; conversation_id may legitimately be empty."""
    cb = _load_callback()
    ctx = _ctx({"customer_id": "cust-a1b2"})

    call = _injected_call(cb(ctx, _request()))
    assert call.args["conversation_id"] == ""
