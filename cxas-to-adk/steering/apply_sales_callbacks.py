"""Attach the Telephony Sales Master's deterministic callbacks (LLM-native design).

Run AFTER create_steering_tree.py (its update_agent can drop callbacks). Installs
EXACTLY these three and ensures NO before_model callback remains:

  - after_model : farewell guard — guarantee the spoken goodbye when the model ends
                  the session (end_session carries no farewell text).   [farewell_callback.py]
  - before_tool : inject the cached ADK session_id into the sales tool so the chat
                  engine resumes by id (skips the per-turn list_sessions lookup).
  - after_tool  : capture the ADK session_id the adapter returns, for reuse next turn.
                  [before_tool + after_tool: session_thread_callbacks.py]

The old forced-tool `before_model` callback (sales_callback.py) is RETIRED: delegation
is now driven by the tool description + instruction (the model self-delegates), so this
script clears any before_model callback to keep the agent matching the live design.

Idempotent: updates in place if a callback of that type exists, else creates; trims
extras so exactly one of each remains.

Config from env: CXAS_PROJECT (REDACTED_PROJECT), CXAS_LOCATION (us).
"""
import os

from cxas_scrapi.core.callbacks import Callbacks

from farewell_callback import AFTER_MODEL_CALLBACK_CODE
from session_thread_callbacks import (
    BEFORE_TOOL_CALLBACK_CODE,
    AFTER_TOOL_CALLBACK_CODE,
)

PROJECT = os.environ.get("CXAS_PROJECT", "REDACTED_PROJECT")
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = "att-ivr-steering"
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
SALES = f"{APP}/agents/telephony-steering"  # Telephony Sales Master leaf

# (callback_type, code, description). before_model is intentionally absent — it is
# cleared below so the retired forced-tool approach never lingers.
CALLBACKS = [
    ("after_model", AFTER_MODEL_CALLBACK_CODE,
     "Guarantee the spoken goodbye plays when the model ends the session."),
    ("before_tool", BEFORE_TOOL_CALLBACK_CODE,
     "Inject the cached ADK session_id into the sales tool (resume by id; skip list_sessions)."),
    ("after_tool", AFTER_TOOL_CALLBACK_CODE,
     "Capture the ADK session_id returned by the sales tool for reuse next turn."),
]


def _callbacks_of(cb, ctype):
    return list(getattr(cb.get_agent(SALES), f"{ctype}_callbacks"))


def _set_one(cb, ctype, code, desc):
    """Ensure EXACTLY one callback of ``ctype`` with this code."""
    existing = _callbacks_of(cb, ctype)
    if existing:
        cb.update_callback(agent_id=SALES, callback_type=ctype, index=0,
                           code=code, description=desc)
        for i in range(len(existing) - 1, 0, -1):
            cb.delete_callback(agent_id=SALES, callback_type=ctype, index=i)
    else:
        cb.create_callback(agent_id=SALES, callback_type=ctype,
                           code=code, description=desc)
    return len(_callbacks_of(cb, ctype))


def _clear(cb, ctype):
    """Remove all callbacks of ``ctype``."""
    for i in range(len(_callbacks_of(cb, ctype)) - 1, -1, -1):
        cb.delete_callback(agent_id=SALES, callback_type=ctype, index=i)


def main():
    print(f"Project={PROJECT} location={LOCATION}\nagent={SALES}")
    cb = Callbacks(app_name=APP)

    # Retire the old forced-tool delegation callback.
    _clear(cb, "before_model")

    for ctype, code, desc in CALLBACKS:
        n = _set_one(cb, ctype, code, desc)
        print(f"  {ctype}: {n}")

    agent = cb.get_agent(SALES)
    inv = {k: len(list(getattr(agent, f"{k}_callbacks")))
           for k in ("before_model", "after_model", "before_tool", "after_tool")}
    print(f"DONE. inventory: {inv}")


if __name__ == "__main__":
    main()
