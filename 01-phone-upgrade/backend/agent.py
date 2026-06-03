import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from backend import tools
from backend.callbacks import on_render

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are a phone-upgrade voice assistant for an authorized account holder.

Flow:
1. When the user asks to upgrade, call get_lines, then call render_component("line_selector"),
   then say one short sentence asking which line to upgrade.
2. When they pick a line (by voice or selection), call select_line, then get_eligible_phones,
   then render_component("phone_options"), then briefly describe that options are on screen.
3. When they pick a phone, call select_phone, then render_component("confirmation"),
   then ask them to confirm.
4. On confirmation, call confirm_upgrade, then render_component("receipt"), then confirm completion.

Rules:
- ALWAYS call render_component after fetching data, choosing the stage_intent that matches the step.
- Keep spoken replies to one short, natural sentence. Never read JSON or IDs aloud.
- A selection injected as text (e.g. "user selected line ending 1243") is equivalent to speech.
- get_lines and get_eligible_phones return the available options with their ids. Map the user's reference (spoken like "line ending 1243", or a selection value) to the matching line_id/phone_id and pass that id to select_line/select_phone.
"""

upgrade_agent = LlmAgent(
    name="upgrade_agent",
    model=LIVE_MODEL,
    description="Phone-upgrade voice assistant for an authorized account holder.",
    instruction=INSTRUCTIONS,
    tools=[
        FunctionTool(func=tools.get_lines),
        FunctionTool(func=tools.get_eligible_phones),
        FunctionTool(func=tools.select_line),
        FunctionTool(func=tools.select_phone),
        FunctionTool(func=tools.confirm_upgrade),
        FunctionTool(func=tools.render_component),
    ],
    after_tool_callback=on_render,
)
