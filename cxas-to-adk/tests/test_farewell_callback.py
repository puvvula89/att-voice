"""Prove the after_model farewell guard against the SAME datamodels + sandbox
preamble CES uses. We exec AFTER_MODEL_CALLBACK_CODE with the callback_libs wildcard
import prepended (what CES injects), then drive it with constructed LlmResponse
objects."""
import cxas_scrapi.utils.callback_libs as clib
from farewell_callback import AFTER_MODEL_CALLBACK_CODE

GOODBYE = "Thank you for contacting AT&T. Have a great day!"


def _load_callback():
    ns = {}
    exec(
        "from cxas_scrapi.utils.callback_libs import *\n" + AFTER_MODEL_CALLBACK_CODE,
        ns,
    )
    return ns["after_model_callback"]


def _resp(*parts):
    return clib.LlmResponse(content=clib.Content(role="model", parts=list(parts)))


def _text(t):
    return clib.Part.from_text(t)


def _end_session():
    return clib.Part.from_function_call("end_session", {"reason": "caller done"})


def _ctx():
    return clib.CallbackContext(state={})


def _has_end(parts):
    return any(p.function_call and p.function_call.name == "end_session" for p in parts)


# --- silent hang-up: end_session with no text -> inject the goodbye -----------

def test_injects_goodbye_when_end_session_is_silent():
    cb = _load_callback()
    out = cb(_ctx(), _resp(_end_session()))
    assert out is not None
    parts = out.content.parts
    assert parts[0].text == GOODBYE            # spoken first
    assert parts[-1].function_call.name == "end_session"   # then terminates


# --- spoke goodbye but forgot end_session -> append end_session (issue 2) -----

def test_appends_end_session_when_goodbye_spoken_without_it():
    cb = _load_callback()
    out = cb(_ctx(), _resp(_text("Thank you for contacting AT&T. Have a great day!")))
    assert out is not None
    parts = out.content.parts
    assert parts[0].text == GOODBYE            # keeps what the model said
    assert _has_end(parts)                     # and now the call actually ends


# --- both present: leave untouched (no double anything) ----------------------

def test_leaves_response_when_both_present():
    cb = _load_callback()
    assert cb(_ctx(), _resp(_text(GOODBYE), _end_session())) is None


# --- not a closing turn: never touch it --------------------------------------

def test_ignores_normal_spoken_turn():
    cb = _load_callback()
    assert cb(_ctx(), _resp(_text("Which line would you like to upgrade?"))) is None


def test_ignores_tool_call_turns():
    cb = _load_callback()
    call = clib.Part.from_function_call("sales_adapter_call_sales_specialist", {"utterance": "x"})
    assert cb(_ctx(), _resp(call)) is None
