"""Deterministic ``before_model`` callback that fires hydration exactly once.

WHAT PROBLEM THIS SOLVES
    The first version of this feature asked the LLM, in the root instruction, to
    "call the hydration tool ONCE at the very start, before greeting". That is a
    soft guarantee in both directions: the model can skip the call on turn 1, and
    it can re-call the tool on turn 5. Neither failure is recoverable from prompt
    wording.

    This callback takes the decision away from the model entirely. It runs
    deterministically in the CES sandbox — plain Python, no model hop, no egress,
    so it costs nothing in latency.

THE RULE IT ENFORCES
    Fire ``hydration_load_prior_conversation`` exactly once per conversation, at
    the very first model step, and ONLY when the ``customer_id`` session variable
    holds a value. Channel-agnostic on purpose: web and telephony run identical
    logic, and whoever populates ``customer_id`` decides whether hydration
    happens. There is no telephony sniffing here.

HOW THE INJECTION WORKS
    Returning an ``LlmResponse`` from a before_model callback REPLACES that model
    step. A ``FunctionCall`` part in that response is executed by the platform
    like any model-emitted call: CES invokes the OpenAPI tool, feeds the result
    back, and re-enters the model — where this callback now returns None, so the
    model speaks its greeting with the hydration result already in context.

THREE INDEPENDENT LOCKS (the tool cannot fire twice)
    1. ``hydrated`` session variable — set the moment we decide, before firing.
       CES persists callback state deltas as session variables across turns.
    2. Scan of ``callback_context.parts()`` for the tool's own call/response —
       turn-local truth, covering any replay inside a single invocation before
       the state delta has landed.
    3. ``llm_request.config.hide_tool(...)`` — once hydration is settled, the
       tool is stripped from the schema the model sees. Not a request to behave;
       the model structurally cannot call it again. This also keeps the
       no-history path clean: a model that never sees a hydration tool cannot
       mention a conversation that does not exist.

RUNTIME CONTRACT (verified against cxas_scrapi.utils.lint_rules.callbacks)
    - CES prepends ``from cxas_scrapi.utils.callback_libs import *``, so
      ``CallbackContext`` / ``LlmRequest`` / ``LlmResponse`` / ``Part`` are
      ambient — but names used in TYPE ANNOTATIONS (``Optional``) must still be
      imported here, or rule C008 fails.
    - The entrypoint MUST be the fully-typed snake_case signature
      ``def before_model_callback(callback_context: CallbackContext,
      llm_request: LlmRequest) -> Optional[LlmResponse]:``. An unannotated
      signature is SILENTLY IGNORED — the callback simply never runs.
    - ``before_agent_callback`` is the wrong hook for this: it returns
      ``Optional[Content]`` and returning content SKIPS the agent rather than
      running a tool.
"""

# Qualified tool name = toolset display_name + operationId.
TOOL = "hydration_load_prior_conversation"

# Session variables. `customer_id` is the gate (supplied by the web client or by
# the telephony variable mapping); `hydrated` is the latch this callback owns.
CUSTOMER_VAR = "customer_id"
LATCH_VAR = "hydrated"
RESUME_VAR = "resume_conversation_id"

# The exact string deployed as Callback.python_code. Kept as source (not a
# Callable) so what the tests exercise is byte-for-byte what runs in the sandbox.
BEFORE_MODEL_CALLBACK_CODE = '''
from typing import Optional

TOOL = "hydration_load_prior_conversation"


def before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Fire hydration once, at conversation start, only when customer_id is set."""

    def hide(request):
        """Take the tool out of the model's schema — it must never call it."""
        if request is not None and request.config is not None:
            request.config.hide_tool(TOOL)

    # Lock 1: already decided on an earlier turn (latch survives the whole session).
    if callback_context.get_variable("hydrated", ""):
        hide(llm_request)
        return None

    # The gate: no customer id -> hydration never happens on this conversation.
    customer_id = (callback_context.get_variable("customer_id", "") or "").strip()
    if not customer_id:
        callback_context.set_variable("hydrated", "skipped")
        hide(llm_request)
        return None

    # Lock 2: the tool already ran earlier in THIS invocation (state delta may
    # not have landed yet, so the latch above cannot be trusted within a turn).
    for part in callback_context.parts():
        if part.has_function_call(TOOL) or part.has_function_response(TOOL):
            callback_context.set_variable("hydrated", "done")
            hide(llm_request)
            return None

    # Latch BEFORE firing, so a retry of this step cannot double-fire.
    callback_context.set_variable("hydrated", "done")
    return LlmResponse.from_parts([
        Part.from_function_call(TOOL, {
            "customer_id": customer_id,
            "conversation_id": callback_context.get_variable(
                "resume_conversation_id", ""
            ) or "",
        })
    ])
'''
