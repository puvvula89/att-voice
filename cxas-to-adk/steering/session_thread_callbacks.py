"""Deterministic session-id threading for the Telephony Sales Master.

Goal: after the first turn, resume the SAME ADK session by id instead of making the
chat engine re-map the caller to a session every turn. resolve_session (in the chat
engine) takes two paths:

    if session_id:  get_session(id)                     # 1 store read -> hydrate
    else:           list_sessions(user_id) -> get_session # 2 store reads

Threading the returned session_id back on every turn takes the first path, dropping
the per-turn ``list_sessions`` round-trip. Hydration is unchanged (get_session is
still needed); we only remove the lookup.

We do this deterministically with two tool callbacks on the Sales Master — NOT by
asking the LLM to echo an opaque id (unreliable) and NOT via instructions:

- before_tool: inject the cached id into the sales tool's ``session_id`` input,
  read from the ``adk_session_id`` session variable (empty on turn 1).
- after_tool: capture the ``session_id`` the adapter returns back into that variable.

CES persists callback state deltas as session variables across turns (same mechanism
the SDK's no-input retry-counter pattern relies on), so the variable survives between
turns without being pre-declared.

Runtime contract (verified against cxas_scrapi.utils.lint_rules.callbacks): the
entrypoints MUST be the fully-typed snake_case signatures below; ``Tool`` /
``CallbackContext`` are ambient (CES prepends the callback_libs wildcard import), but
annotation names ``Any`` / ``Optional`` must be imported here (rule C008). Returning
None runs the tool with the (mutated) input / leaves the response unchanged; the
before_tool mutates ``input`` in place, the after_tool only reads ``tool_response``.
"""

TOOL = "sales_adapter_call_sales_specialist"
SESSION_VAR = "adk_session_id"

# --- before_tool: inject the cached session_id into the sales tool input -------
BEFORE_TOOL_CALLBACK_CODE = '''
from typing import Any, Optional


def before_tool_callback(
    tool: Tool, input: dict[str, Any], callback_context: CallbackContext
) -> Optional[dict[str, Any]]:
    """Resume the cached ADK session by id (skips the engine's per-turn list_sessions)."""
    if tool.name == "sales_adapter_call_sales_specialist":
        sid = callback_context.get_variable("adk_session_id", "")
        if sid:
            input["session_id"] = sid
    return None
'''

# --- after_tool: capture the session_id the adapter returned -------------------
AFTER_TOOL_CALLBACK_CODE = '''
from typing import Any, Optional


def after_tool_callback(
    tool: Tool,
    input: dict[str, Any],
    callback_context: CallbackContext,
    tool_response: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Remember the ADK session_id so later turns resume it by id."""
    if tool.name == "sales_adapter_call_sales_specialist":
        sid = (tool_response or {}).get("session_id")
        if sid:
            callback_context.set_variable("adk_session_id", sid)
    return None
'''
