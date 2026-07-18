"""Deterministic ``before_model`` callback for the Telephony Sales Master.

Problem it solves: the Sales Master is *instructed* to call ``call_sales_specialist``
(the OpenAPI tool that reaches the ADK sales brain) every turn, but an LLM tool call
is reliable-not-guaranteed — on an emotionally-framed turn the model was observed
answering directly and skipping the tool (adapter logs showed zero requests). This
callback removes the discretion: it returns an ``LlmResponse`` carrying the
``call_sales_specialist`` FunctionCall, and CES executes it as if the model emitted
it. No DFCX, no egress in the callback (the OpenAPI toolset does the HTTP).

Runtime contract (verified against the SDK's callback linter,
cxas_scrapi.utils.lint_rules.callbacks):
- CES prepends ``from cxas_scrapi.utils.callback_libs import *`` before this code,
  so ``CallbackContext``/``LlmRequest``/``LlmResponse``/``Content``/``Part`` are
  ambient — but names used in TYPE ANNOTATIONS (``Optional``) must still be imported
  here (rule C008), so we ``from typing import Optional``.
- The entrypoint MUST be the fully-typed snake_case signature
  ``def before_model_callback(callback_context: CallbackContext,
  llm_request: LlmRequest) -> Optional[LlmResponse]:`` (rules C001/C002/C003/C009,
  all ERROR). An UNANNOTATED signature is silently ignored by the platform — the
  callback never fires and the model free-runs (observed live: the Sales Master
  leaked chain-of-thought and never called the tool). Returning an ``LlmResponse``
  short-circuits the model (forces the tool); returning ``None`` lets the model run.

Utterance source (correctness across transfers): the caller's real words come from
``callback_context.user_content`` — the user turn that STARTED the invocation. A
CES transfer (Concierge -> Consumer -> Sales) happens WITHIN one invocation, so
``user_content`` stays the caller's words, whereas ``llm_request.contents`` gets a
SYNTHETIC ``<context> ... transfer_to_agent ... </context>`` pseudo user turn — the
old code forwarded THAT to the specialist, which produced a dead "One moment,
please." reply and a re-greeting. We fall back to ``get_last_user_input()`` then a
synthetic-filtered scan of ``contents``; if none yields genuine words we return None
(defer to the model) rather than fabricate intent. This mirrors the SDK's own
canonical pattern (``cxas_scrapi.migration.prompts`` uses ``get_last_user_input``).

Loop guard: ``before_model`` also fires AFTER the tool returns (so the model can
speak the reply). If ``call_sales_specialist`` already ran this turn, return None so
the model voices the tool result instead of delegating again forever.

Farewell/end_session is intentionally NOT handled here (the linter discourages
hardcoded intent-phrase lists in callbacks — rule C005 — "keep detection in
instructions, callbacks for execution only"). Terminating the call is a follow-up.

session_id is intentionally omitted: ADK resolves the caller's latest session by
user_id (customer_id) within the 10-min resume TTL, so the caller stays on one
session without the callback threading an id.
"""

# The exact string deployed as Callback.python_code. Kept as source (not a Callable)
# so what we test locally is byte-for-byte what runs in the CES sandbox.
BEFORE_MODEL_CALLBACK_CODE = '''
from typing import Optional


def _genuine_text(parts):
    """Join the caller's spoken/typed text from a list of Parts, dropping tool
    calls/responses and SYNTHETIC steering messages. When CES routes the caller into
    this agent it renders the hand-off as a pseudo user turn like
    "<context> [Consumer Steering] `transfer_to_agent` tool returned result: {}
    </context>" — that is routing metadata, NOT the caller's words. Forwarding it to
    the specialist produced a dead "One moment, please." turn and a re-greeting."""
    chunks = []
    for p in (parts or []):
        if p.function_call is not None or p.function_response is not None:
            continue
        t = p.text_or_transcript()
        if not t:
            continue
        low = t.lower()
        if "<context>" in low or "transfer_to_agent" in low or "tool returned result" in low:
            continue
        chunks.append(t.strip())
    return " ".join(c for c in chunks if c).strip()


def before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Force the sales tool on every substantive Sales-Master turn, delegating the
    caller's REAL utterance to the ADK specialist."""
    # Runtime name of an OpenAPI-toolset operation is DisplayName_OperationId
    # (toolset 'sales_adapter' + op 'call_sales_specialist'). The bare operation id
    # does not resolve at runtime — must be the qualified name here.
    tool = "sales_adapter_call_sales_specialist"
    contents = list(llm_request.contents) if llm_request and llm_request.contents else []

    # Loop guard: walk this turn's tail back to the most recent user message; if the
    # tool's call/response is already present, let the model speak the reply.
    for content in reversed(contents):
        for part in (content.parts or []):
            fr = part.function_response
            fc = part.function_call
            if (fr is not None and fr.name == tool) or (fc is not None and fc.name == tool):
                return None
        if content.role == "user":
            break

    # The caller's ACTUAL words. Source order matters for correctness across the
    # Concierge -> Consumer -> Sales transfer chain:
    #  1. callback_context.user_content — the user turn that STARTED this invocation.
    #     Transfers happen WITHIN one invocation, so this stays the caller's real
    #     words (not the synthetic transfer turn that appears in llm_request.contents).
    #  2. get_last_user_input() — the last real user event, if user_content is unset.
    #  3. request contents — last resort.
    # Every source is synthetic-filtered, so routing metadata is never forwarded.
    utterance = ""
    uc = callback_context.user_content
    if uc is not None:
        utterance = _genuine_text(uc.parts)
    if not utterance:
        utterance = _genuine_text(callback_context.get_last_user_input())
    if not utterance:
        for content in reversed(contents):
            if content.role == "user":
                cand = _genuine_text(content.parts)
                if cand:
                    utterance = cand
                    break

    # No genuine caller utterance recoverable (e.g. a bare hand-off turn or a
    # silence/no-input system event). Do NOT fabricate intent — hand back to the
    # model, which has the full conversation and can compose the right tool call
    # itself. This keeps the callback intent-agnostic for any request/any agent.
    if not utterance:
        return None

    # Farewell: hand back to the model (return None) so it says the closing line and
    # runs its end_session step (the specialist is NOT called, so there is exactly
    # ONE goodbye — the model's). Normalize punctuation/commas so multi-word closers
    # like "No, that's it." are caught and don't leak through to the specialist
    # (which then said its own goodbye on top of the model's -> the double we saw).
    closer = " ".join(utterance.lower().replace(",", " ").split()).strip(".!?, ")
    closers = (
        "no", "nope", "nothing else", "that's all", "thats all", "that is all",
        "i'm good", "im good", "no thanks", "no thank you", "we're done", "were done",
        "goodbye", "bye", "all set", "that will be all", "i'm done", "im done",
        "that's it", "thats it", "no that's it", "no thats it", "no that's all",
        "no thats all", "no im done", "no i'm done",
    )
    if (
        closer in closers
        or "nothing else" in closer
        or "that's all" in closer
        or "thats all" in closer
        or "that's it" in closer
        or "thats it" in closer
    ):
        return None

    customer_id = callback_context.get_variable("customer_id", "wilson")
    return LlmResponse.from_parts([
        Part.from_function_call(
            tool, {"customer_id": customer_id, "utterance": utterance}
        )
    ])
'''
