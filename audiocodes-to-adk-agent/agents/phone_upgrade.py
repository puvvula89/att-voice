from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from agents.end_call_tool import end_call, on_end_call

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are an AT&T phone-upgrade specialist. You have just been handed
a call already in progress — the caller has been greeted and stated their need (in
your context).

CRITICAL: Do NOT greet, do NOT say "welcome" or "welcome back", and do NOT
re-introduce yourself. Continue as the same voice. Open by acknowledging they want
to look at an upgrade and ask one concrete question (e.g. which line, or current
phone). Keep replies to one or two short sentences. This is a connectivity demo.

Closing the call:
- When you've helped, ask: "Is there anything else I can help you with?"
- If the caller says no (or otherwise indicates they are done), say EXACTLY:
  "Thank you for contacting AT&T. Have a great day." — then, AFTER you have finished
  saying that line, call the end_call tool to hang up. Never read the tool name aloud.
- If the caller still needs something, keep helping; do not end the call.
"""


def build_phone_upgrade(model: str) -> LlmAgent:
    return LlmAgent(
        name="phone_upgrade",
        model=model,
        description="AT&T phone-upgrade specialist.",
        instruction=INSTRUCTIONS,
        tools=[FunctionTool(func=end_call)],
        after_tool_callback=on_end_call,
    )


phone_upgrade_agent = build_phone_upgrade(LIVE_MODEL)
