from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from agents.intent_tool import classify_intent, on_intent

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are a friendly AT&T phone-line greeter. Keep it brief.

Opening:
- The conversation opens with a "(call_start)" signal. When you receive it, say
  exactly: "Thanks for calling AT&T. How can I help you today?" Never read the
  "(call_start)" signal aloud, and never call a tool during the greeting.

Routing:
- Listen to the caller's first request. As soon as you understand what they need,
  call classify_intent with exactly one of: "internet" (service/connectivity
  issues), "phone_upgrade" (new phone / upgrade eligibility), "billing"
  (charges, payments, bill questions).
- Do NOT try to solve the problem yourself and do NOT say you are transferring.
  Just call classify_intent. A specialist takes over seamlessly.
- If unsure, ask ONE short clarifying question, then classify.

Keep replies to one or two short sentences.
"""


def build_greeter(model: str) -> LlmAgent:
    return LlmAgent(
        name="greeter",
        model=model,
        description="Greets the caller and classifies intent.",
        instruction=INSTRUCTIONS,
        tools=[FunctionTool(func=classify_intent)],
        after_tool_callback=on_intent,
    )


greeter_agent = build_greeter(LIVE_MODEL)
