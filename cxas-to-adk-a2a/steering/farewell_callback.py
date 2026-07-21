"""Deterministic ``after_model`` callback for the Telephony Sales Master.

Problem it solves: the Sales Master is *instructed* to say the closing line AND call
``end_session`` in the same turn when the caller is done. The model does one or the
other unreliably (a known Gemini behaviour around a terminal tool): sometimes it hangs
up silently (``end_session`` with no spoken line), sometimes it speaks the goodbye but
never calls ``end_session`` (so the call never ends). ``end_session`` itself carries no
farewell text (only a ``reason``), so the goodbye must be a separate text Part.

This callback runs AFTER the model, deterministically, in the CES sandbox — plain
Python, NOT another model call, so it adds no latency and no egress. It leaves the
intent decision to the LLM (WHEN to close) and only guarantees EXECUTION: on a closing
turn it makes the response contain BOTH, exactly once, spoken line first —

  - ``end_session`` present, no text   -> prepend the closing line
  - closing line spoken, no end_session -> append ``end_session`` (fixes the call
                                           that never ended)
  - both present                        -> leave untouched (no double anything)

A turn is "closing" if the model emitted ``end_session`` OR spoke our own authored
farewell line ("...have a great day..."). Matching our own line — not the caller's
arbitrary words — keeps this execution-only, not intent detection.

Runtime contract (verified against cxas_scrapi.utils.lint_rules.callbacks):
- CES prepends ``from cxas_scrapi.utils.callback_libs import *`` before this code, so
  ``CallbackContext``/``LlmResponse``/``Content``/``Part`` are ambient — but names in
  TYPE ANNOTATIONS (``Optional``) must still be imported (rule C008), hence
  ``from typing import Optional``.
- The entrypoint MUST be the fully-typed snake_case signature
  ``def after_model_callback(callback_context: CallbackContext,
  llm_response: LlmResponse) -> Optional[LlmResponse]:`` (an unannotated signature is
  silently ignored). Returning an ``LlmResponse`` replaces the model output;
  returning ``None`` leaves it unchanged.
"""

# The exact string deployed as Callback.python_code. Kept as source (not a Callable)
# so what we test locally is byte-for-byte what runs in the CES sandbox.
AFTER_MODEL_CALLBACK_CODE = '''
from typing import Optional


def after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """On a closing turn, guarantee BOTH the spoken goodbye and end_session."""
    goodbye = "Thank you for contacting AT&T. Have a great day!"

    content = llm_response.content if llm_response else None
    parts = list(content.parts) if content and content.parts else []

    end_part = None
    for p in parts:
        if p.function_call is not None and p.function_call.name == "end_session":
            end_part = p
            break
    text_parts = [p for p in parts if (p.text or "").strip()]
    spoke_goodbye = "have a great day" in " ".join((p.text or "") for p in text_parts).lower()

    # Only act when the model is CLOSING the call this turn.
    if end_part is None and not spoke_goodbye:
        return None

    # Already complete — it spoke a line AND called end_session: leave it.
    if end_part is not None and text_parts:
        return None

    # Guarantee both, exactly once, spoken line first then end_session:
    #  - keep whatever the model spoke, or supply the goodbye if it said nothing;
    #  - keep its end_session, or add one if it forgot (the call that never ended).
    speak = text_parts if text_parts else [Part.from_text(goodbye)]
    end = [end_part] if end_part is not None else [Part.from_end_session(reason="caller finished")]
    return LlmResponse.from_parts(speak + end)
'''
