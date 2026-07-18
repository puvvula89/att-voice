"""Prove the deterministic before_model callback logic against the SAME datamodels
and sandbox preamble CES uses — no live CES call (429 quota) needed.

We exec the exact ``BEFORE_MODEL_CALLBACK_CODE`` string with the callback_libs
wildcard import prepended (that is literally what CES injects), then drive it with
constructed CallbackContext / LlmRequest objects. The callback reads only
``llm_request.contents``.
"""
import cxas_scrapi.utils.callback_libs as clib
from sales_callback import BEFORE_MODEL_CALLBACK_CODE

TOOL = "sales_adapter_call_sales_specialist"


def _load_callback():
    ns = {}
    exec(
        "from cxas_scrapi.utils.callback_libs import *\nimport json\n"
        + BEFORE_MODEL_CALLBACK_CODE,
        ns,
    )
    return ns["before_model_callback"]


def _user(text):
    return clib.Content(role="user", parts=[clib.Part.from_text(text)])


def _model_call(args=None):
    return clib.Content(
        role="model",
        parts=[clib.Part.from_function_call(TOOL, args or {"customer_id": "wilson", "utterance": "x"})],
    )


def _tool_response():
    return clib.Content(
        role="user",
        parts=[clib.Part.from_function_response(TOOL, {"reply": "Which line?"})],
    )


def _ctx(customer_id="wilson-demo-01", user_content=None, events=None):
    kw = {"state": {"customer_id": customer_id}}
    if user_content is not None:
        kw["user_content"] = user_content
    if events is not None:
        kw["events"] = events
    return clib.CallbackContext(**kw)


def _event(author, content):
    return clib.Event(
        id="e", author=author, timestamp=0, invocation_id="i", content=content
    )


def _req(*contents):
    return clib.LlmRequest(contents=list(contents))


# The synthetic pseudo user turn CES renders into the model prompt on a transfer.
TRANSFER_BLOB = "<context> [Consumer Steering] `transfer_to_agent` tool returned result: {} </context>"


# --- forces the tool on a substantive turn -----------------------------------

def test_forces_tool_call_on_substantive_turn():
    cb = _load_callback()
    resp = cb(_ctx(), _req(_user("upgrade my iPhone")))
    assert resp is not None                      # short-circuits the model
    part = resp.content.parts[0]
    assert part.function_call.name == TOOL
    assert part.function_call.args["customer_id"] == "wilson-demo-01"
    assert part.function_call.args["utterance"] == "upgrade my iPhone"


def test_customer_id_defaults_to_wilson_when_unset():
    cb = _load_callback()
    ctx = clib.CallbackContext(state={})
    resp = cb(ctx, _req(_user("iPhone 16 deals")))
    assert resp.content.parts[0].function_call.args["customer_id"] == "wilson"


def test_uses_most_recent_user_message_as_utterance():
    cb = _load_callback()
    # History before the current user turn must be ignored for the utterance.
    resp = cb(_ctx(), _req(_user("old"), _model_call(), _tool_response(), _user("trade in my phone")))
    assert resp is not None
    assert resp.content.parts[0].function_call.args["utterance"] == "trade in my phone"


# --- loop guard: don't re-delegate after the tool already ran this turn ------

def test_returns_none_after_already_delegated_this_turn():
    """After the tool ran, before_model fires again so the model can SPEAK the
    reply — it must not delegate a second time (infinite loop)."""
    cb = _load_callback()
    assert cb(_ctx(), _req(_user("upgrade"), _model_call(), _tool_response())) is None


def test_returns_none_when_only_the_model_call_is_present():
    """Between the forced call and its response, before_model must not re-fire the
    tool either."""
    cb = _load_callback()
    assert cb(_ctx(), _req(_user("upgrade"), _model_call())) is None


# --- farewell guard: let the model reach end_session ------------------------

def test_returns_none_on_farewell_so_end_session_can_fire():
    cb = _load_callback()
    for phrase in ("no", "Nothing else, thanks.", "that's all", "I'm good", "bye"):
        assert cb(_ctx(), _req(_user(phrase))) is None, phrase


def test_no_within_a_real_request_still_delegates():
    """A 'no' that is part of an actual request must NOT be treated as a farewell."""
    cb = _load_callback()
    resp = cb(_ctx(), _req(_user("no, the iPhone 16 please")))
    assert resp is not None
    assert resp.content.parts[0].function_call.name == TOOL


def test_multiword_closer_with_comma_is_treated_as_farewell():
    """'No, that's it.' must be caught as a closer (not leaked to the specialist,
    which then said its own goodbye on top -> the doubled farewell)."""
    cb = _load_callback()
    for phrase in ("No, that's it.", "No, that's all.", "That's it, thanks!"):
        assert cb(_ctx(), _req(_user(phrase))) is None, phrase


# --- transfer handling: forward the caller's REAL words, never the hand-off blob --

def test_uses_user_content_across_transfer():
    """The real runtime shape: user_content holds the turn that started the
    invocation (the caller's words), while contents shows the synthetic transfer
    blob. The specialist must receive the caller's words, not routing metadata."""
    cb = _load_callback()
    ctx = _ctx(user_content=_user("I want to upgrade my phone"))
    resp = cb(ctx, _req(_user(TRANSFER_BLOB)))
    assert resp is not None
    assert resp.content.parts[0].function_call.args["utterance"] == "I want to upgrade my phone"


def test_uses_last_user_event_when_user_content_absent():
    """Fallback: recover the caller's words from the events (last real user turn),
    ignoring the trailing agent transfer event."""
    cb = _load_callback()
    ctx = _ctx(events=[
        _event("user", _user("trade in my Pixel")),
        _event("consumer-steering", clib.Content(role="model", parts=[clib.Part.from_agent_transfer("Telephony Sales Master")])),
    ])
    resp = cb(ctx, _req(_user(TRANSFER_BLOB)))
    assert resp is not None
    assert resp.content.parts[0].function_call.args["utterance"] == "trade in my Pixel"


def test_prefers_genuine_utterance_over_transfer_notice_in_contents():
    """Last-resort contents scan still skips the synthetic blob."""
    cb = _load_callback()
    resp = cb(_ctx(), _req(_user("I want to upgrade my phone"), _user(TRANSFER_BLOB)))
    assert resp is not None
    assert resp.content.parts[0].function_call.args["utterance"] == "I want to upgrade my phone"


def test_defers_to_model_when_only_transfer_blob_and_no_real_utterance():
    """If NO genuine caller words are recoverable, do not fabricate intent — return
    None so the model (which has full context) composes the tool call itself."""
    cb = _load_callback()
    assert cb(_ctx(), _req(_user(TRANSFER_BLOB))) is None


def test_delegates_again_on_a_new_user_turn():
    """A fresh user turn AFTER a completed delegation must delegate again."""
    cb = _load_callback()
    resp = cb(_ctx(), _req(
        _user("upgrade"), _model_call(), _tool_response(), _user("the one ending 1243"),
    ))
    assert resp is not None
    assert resp.content.parts[0].function_call.args["utterance"] == "the one ending 1243"
