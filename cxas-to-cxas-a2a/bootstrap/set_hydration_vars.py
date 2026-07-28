"""Flip the hydration test variables on the voice app.

    # show current values
    python bootstrap/set_hydration_vars.py

    # arm hydration: identify the customer and point at a prior conversation
    python bootstrap/set_hydration_vars.py --customer-id cust-wilson \
                                           --conversation-id <PRIOR_SESSION_UUID>

    # disarm: back to the cold-start path (agent greets normally, tool never fires)
    python bootstrap/set_hydration_vars.py --clear

WHY THIS EXISTS
    These are APP-LEVEL variable defaults, so they seed every NEW session. The
    relay pins a session id but does not set variables, so for a manual test the
    default is the lever. In production `customer_id` would be populated per
    session — by the web client's identity, or by the telephony variable mapping
    on GTP — and this script is only a test harness.

REMEMBER
    `customer_id` is the GATE. Empty means the before_model callback never fires
    hydration at all, whatever `resume_conversation_id` says. `hydrated` is owned
    by the callback; it is listed here only so you can see it latch.
"""
import argparse
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.variables import Variables, VariableType

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

CUSTOMER_VAR = "customer_id"
RESUME_VAR = "resume_conversation_id"
LATCH_VAR = "hydrated"


def _default_of(variable) -> str:
    """Pull the plain default string out of a VariableDeclaration.

    Asymmetric on purpose: WRITING requires an explicit protobuf Value
    ({"string_value": ...}), but READING gives a plain Python str back, because
    proto-plus unmarshals google.protobuf.Value for you. Handle both shapes —
    assuming the write shape on the read side silently yields "" for every
    variable, which reads as "nothing was saved" when in fact it was.
    """
    schema = getattr(variable, "schema", None)
    default = getattr(schema, "default", None) if schema is not None else None
    if default is None:
        return ""
    if isinstance(default, str):
        return default
    return getattr(default, "string_value", "") or ""


def _set(variables, name, value):
    """Rewrite one variable's default.

    Two SDK potholes are avoided here, both verified against the live app:

    1. NOT Variables.update_variable — broken in this build: it reaches for
       types.App.VariableDeclaration.Schema, a nested type that does not exist,
       and dies with AttributeError.
    2. `default` is a google.protobuf.Value, so it MUST be given as
       {"string_value": ...}. Handing it a bare Python string (as the SDK's own
       create_variable does) is accepted silently and stores an EMPTY value —
       the write looks like it succeeded and nothing lands.
    """
    try:
        app = variables.get_app(variables.app_name)
        declarations = [v for v in app.variable_declarations if v.name != name]
        declarations.append(
            T.App.VariableDeclaration(
                name=name,
                schema={
                    "type_": VariableType.STRING.value,
                    "default": {"string_value": value},
                },
            )
        )
        variables.update_app(variables.app_name, variable_declarations=declarations)
        print(f"   set {name} = {value!r}")
    except Exception as e:
        print(f"   {name}: FAILED {type(e).__name__}: {str(e)[:140]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customer-id", help="the gate — non-empty arms hydration")
    ap.add_argument("--conversation-id", help="prior conversation (== its session UUID)")
    ap.add_argument("--clear", action="store_true", help="blank both, disarming hydration")
    args = ap.parse_args()

    variables = Variables(app_name=APP)
    print(f"app={APP_ID}")

    if args.clear:
        print("\nDisarming hydration (cold-start path)")
        _set(variables, CUSTOMER_VAR, "")
        _set(variables, RESUME_VAR, "")
        _set(variables, LATCH_VAR, "")
    elif args.customer_id is not None or args.conversation_id is not None:
        print("\nArming hydration")
        if args.customer_id is not None:
            _set(variables, CUSTOMER_VAR, args.customer_id)
        if args.conversation_id is not None:
            _set(variables, RESUME_VAR, args.conversation_id)
        # A stale latch would make a fresh session think it already hydrated.
        _set(variables, LATCH_VAR, "")

    # Read back from the server — never report state from the flags we passed.
    print("\nCurrent values")
    current = {}
    for name in (CUSTOMER_VAR, RESUME_VAR, LATCH_VAR):
        try:
            current[name] = _default_of(variables.get_variable(name))
            print(f"   {name} = {current[name]!r}")
        except Exception as e:
            print(f"   {name}: (unreadable: {type(e).__name__})")

    armed = bool(current.get(CUSTOMER_VAR))
    print(f"\nhydration is {'ARMED' if armed else 'DISARMED (customer_id empty)'}")
    print("Reminder: GTP channels are VERSION-PINNED — for a telephony test you must")
    print("cut a NEW version and repoint the channel. The web client always uses the")
    print("draft, so it picks these up immediately.")


if __name__ == "__main__":
    main()
