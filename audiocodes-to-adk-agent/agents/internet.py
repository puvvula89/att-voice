from __future__ import annotations

import os

from google.adk.agents import LlmAgent

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are an AT&T internet-support specialist. You have just been
handed a call that is already in progress — the caller has already been greeted and
has told us their issue (it is in your context).

CRITICAL: Do NOT greet, do NOT say "hello", do NOT say "welcome" or "welcome back",
and do NOT re-introduce yourself. Continue the existing conversation as if you were
the same voice. Open by acknowledging their internet issue and asking one concrete
troubleshooting question. Keep replies to one or two short sentences. This is a
connectivity demo; a couple of helpful turns is enough.
"""


def build_internet(model: str) -> LlmAgent:
    return LlmAgent(
        name="internet",
        model=model,
        description="AT&T internet-support specialist.",
        instruction=INSTRUCTIONS,
    )


internet_agent = build_internet(LIVE_MODEL)
