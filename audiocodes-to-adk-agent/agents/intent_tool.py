from __future__ import annotations

VALID_INTENTS = ("internet", "phone_upgrade", "billing")


def classify_intent(intent: str) -> dict:
    """Record the caller's intent. Call this once you know what the caller needs.

    intent must be one of: internet, phone_upgrade, billing.
    """
    return {"status": "classified", "intent": intent}


def on_intent(tool, args, tool_context, tool_response):
    """after_tool_callback: stage the intent into session state for the relay.

    The relay reads it from the run_live event's actions.state_delta.intent.
    """
    if tool.name == "classify_intent":
        tool_context.state["intent"] = args.get("intent", "")
    return None
