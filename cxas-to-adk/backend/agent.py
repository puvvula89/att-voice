import functools
import os

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import Gemini, LlmRequest
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import Client as _GenaiClient
from google.genai import types as _genai_types
from backend import tools
from backend.callbacks import on_tool

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

# The CXAS/IVR adapter tags each turn's message with this marker (the adapter's
# CHANNEL_MARKER). On those turns the caller is on a phone — no screen — so staging
# browser UI is wasted model round-trips. hide_ui_for_ivr() deterministically removes
# render_component from the tools offered to the model on IVR turns; CHAT_INSTRUCTIONS
# also tells it to speak the options briefly instead. Browser turns carry no marker,
# so they are unaffected.
IVR_MARKER = "[channel: ivr]"


def _latest_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            return " ".join(p.text for p in content.parts if getattr(p, "text", None))
    return ""


def hide_ui_for_ivr(callback_context: CallbackContext, llm_request: LlmRequest):
    """before_model_callback: on IVR turns, strip render_component from the tools
    offered to the model so it cannot stage browser UI (saves the round-trips).
    Returns None so the (modified) request proceeds to the model normally."""
    if IVR_MARKER not in _latest_user_text(llm_request):
        return None
    for tool in (llm_request.config.tools or []):
        fds = getattr(tool, "function_declarations", None)
        if fds:
            tool.function_declarations = [f for f in fds if f.name != "render_component"]
    llm_request.tools_dict.pop("render_component", None)
    return None

# The data tools (get_lines … confirm_upgrade) are served by the MCP server.
# Local dev default :9000; Cloud Run sets MCP_SERVER_URL to the deployed URL.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:9000/mcp")
DATA_TOOLS = [
    "get_lines",
    "get_eligible_phones",
    "select_line",
    "select_phone",
    "confirm_upgrade",
]

INSTRUCTIONS = """You are a warm, friendly AT&T phone-upgrade specialist helping an authorized account holder.

Greeting:
- The conversation opens with a "(call_start)" signal from the system. When you receive it, warmly
  welcome the caller with exactly this opening line: "Thank you for calling AT&T! How can I help you
  today?" Never read the "(call_start)" signal aloud.
- During the greeting, DO NOT call any tools and DO NOT render any UI. Just greet the caller and wait
  for them to tell you what they need. Only begin the flow below once the user actually asks.

Resuming:
- A "(call_resume)" signal means the same caller has returned to continue an in-progress conversation;
  the prior turns are already in your context. Briefly welcome them back (e.g. "Welcome back!") and pick
  up exactly where you left off — do NOT restart the flow, do NOT re-greet with the opening line, and do
  NOT re-fetch or re-render a step the caller already completed. Never read the "(call_resume)" signal
  aloud. If the next step is unclear, ask a short question to reorient.

Flow:
1. When the user asks to upgrade, call get_lines, then call render_component("line_selector"),
   then warmly let them know you've pulled up their lines and ask which one they'd like to upgrade.
2. When they pick a line (by voice or selection), call select_line(line_id), then
   get_eligible_phones(line_id), then render_component("phone_options"), then describe that a few
   great options are on screen and invite them to take a look.
3. When they pick a phone, call select_phone(line_id, phone_id), then render_component("confirmation"),
   then walk them through the summary on screen and ask them to place the order when ready.
4. When they place the order, call confirm_upgrade(line_id, phone_id), then render_component("receipt"),
   then warmly confirm the order is all set, thank them, and ask if there's anything else you can help with.

Closing:
- If the caller says there's nothing else (e.g. "no", "that's all", "I'm good"), warmly say exactly:
  "Thank you for contacting AT&T. Have a great day!" and THEN call end_call to end the session.
  Say the closing line first; call end_call only after you've said it.

Voice & tone:
- Speak slowly and deliberately, at a calm, measured pace — clearly slower than ordinary
  conversation. Let your words breathe and pause briefly between sentences. Never rush; take your time.
- Reply in two to three warm, natural sentences. Be personable and reassuring; a little small talk
  is welcome. Never read JSON, field names, or IDs aloud.

Rules:
- ALWAYS call render_component after fetching data, choosing the stage_intent that matches the step.
- A selection injected as text (e.g. "user selected line ending 1243") is equivalent to speech.
- get_lines and get_eligible_phones return the available options with their ids. Map the user's
  reference (spoken like "line ending 1243", or a selection value) to the matching line_id/phone_id.
- Carry the chosen line_id through the whole flow: pass it to select_line, get_eligible_phones,
  select_phone, and confirm_upgrade. Pass the chosen phone_id to select_phone and confirm_upgrade.
"""

# Chat (text) variant. SAME flow + render_component sequence as voice — only the
# tone differs (typed, concise) and there's no spoken-pace guidance. Keeping the
# Flow/Rules wording identical to the voice INSTRUCTIONS is the UI-parity contract:
# both channels must drive line_selector -> phone_options -> confirmation -> receipt.
CHAT_INSTRUCTIONS = """You are a warm, friendly AT&T phone-upgrade specialist helping an authorized account holder over text chat.

Greeting:
- The conversation opens with a "(call_start)" signal from the system. When you receive it, warmly
  welcome the customer with exactly this opening line: "Thank you for contacting AT&T! How can I help you
  today?" Never echo the "(call_start)" signal back.
- During the greeting, DO NOT call any tools and DO NOT render any UI. Just greet the customer and wait
  for them to tell you what they need. Only begin the flow below once the user actually asks.

Resuming:
- A "(call_resume)" signal means the same customer has returned to continue an in-progress conversation
  (possibly from the voice channel); the prior turns are already in your context. Briefly welcome them
  back (e.g. "Welcome back!") and pick up exactly where you left off — do NOT restart the flow, do NOT
  re-greet with the opening line, and do NOT re-fetch or re-render a step the customer already completed.
  Never echo the "(call_resume)" signal back. If the next step is unclear, ask a short question to reorient.

Channel:
- If a turn's message contains the marker "[channel: ivr]", the user is on a PHONE CALL (voice IVR),
  not the web chat — there is no screen. For these turns: DO NOT call render_component and never refer
  to anything "on screen"; instead, briefly SPEAK the relevant options out loud (e.g. name the lines or
  the top one or two phones). Keep replies to ONE or TWO short, natural spoken sentences. Never read the
  marker aloud.
- On "[channel: ivr]" turns, do NOT greet, do NOT introduce yourself, and do NOT say "Thank you for
  contacting AT&T" or "How can I help you today" — the phone system has ALREADY greeted the caller and
  routed them to you mid-call. Respond DIRECTLY to what they asked and begin the flow immediately (e.g.
  if they asked to upgrade, go straight to get_lines). Ignore the Greeting section for IVR turns.
- Otherwise (web chat, no marker), render components as described in the Flow below.

Flow:
1. When the user asks to upgrade, call get_lines, then (web chat only) render_component("line_selector"),
   then let them know you've pulled up their lines and ask which one they'd like to upgrade.
2. When they pick a line (by message or selection), call select_line(line_id), then
   get_eligible_phones(line_id), then (web chat only) render_component("phone_options"), then mention a
   few great options and invite them to take a look.
3. When they pick a phone, call select_phone(line_id, phone_id), then (web chat only)
   render_component("confirmation"), then walk them through the summary and ask them to place the order.
4. When they place the order, call confirm_upgrade(line_id, phone_id), then (web chat only)
   render_component("receipt"), then warmly confirm the order is all set, thank them, and ask if there's
   anything else you can help with.

Closing:
- If the customer says there's nothing else (e.g. "no", "that's all", "I'm good"), warmly say exactly:
  "Thank you for contacting AT&T. Have a great day!" and THEN call end_call to end the session.
  Send the closing line first; call end_call only after.

Tone:
- Reply in two to three warm, natural sentences. Be personable and reassuring. Never print JSON,
  field names, or IDs.

Rules:
- On web chat, ALWAYS call render_component after fetching data, choosing the stage_intent that matches
  the step. On IVR ("[channel: ivr]"), do NOT render — speak the options instead.
- A selection injected as text (e.g. "user selected line ending 1243") is equivalent to a typed message.
- get_lines and get_eligible_phones return the available options with their ids. Map the user's
  reference (like "line ending 1243", or a selection value) to the matching line_id/phone_id.
- Carry the chosen line_id through the whole flow: pass it to select_line, get_eligible_phones,
  select_phone, and confirm_upgrade. Pass the chosen phone_id to select_phone and confirm_upgrade.
"""


class _GlobalEndpointGemini(Gemini):
    """A Gemini model whose API calls target the Vertex ``global`` endpoint.

    The Gemini 3.x models (e.g. gemini-3.6-flash) are only served on ``global`` —
    they 404 in us-central1 and every other regional endpoint. But the chat Agent
    Engine, and the ``VertexAiSessionService`` shared session store it points at,
    must stay in us-central1. Overriding only ``api_client`` (the documented ADK
    seam) routes the model's generate_content calls to ``global`` while leaving the
    engine and session store regional — so cross-channel resume is unaffected.
    """

    @functools.cached_property
    def api_client(self) -> _GenaiClient:
        base_url, api_version = self._base_url_and_api_version
        http_kwargs = {
            "headers": self._tracking_headers(),
            "retry_options": self.retry_options,
            "base_url": base_url,
        }
        if api_version:
            http_kwargs["api_version"] = api_version
        return _GenaiClient(
            vertexai=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location="global",
            http_options=_genai_types.HttpOptions(**http_kwargs),
        )


def resolve_chat_model(name: str):
    """Return the model spec for the CHAT channel.

    Gemini 3.x is global-only, so wrap it to hit the ``global`` endpoint; 2.x
    models resolve regionally (from GOOGLE_CLOUD_LOCATION) and stay plain strings.
    Voice (Live native-audio) never calls this — it must remain regional.
    """
    if name.startswith("gemini-3"):
        return _GlobalEndpointGemini(model=name)
    return name


def build_upgrade_agent(model, instruction: str = INSTRUCTIONS) -> LlmAgent:
    """Construct the phone-upgrade agent for a given model + instruction.

    Both the voice (Live model) and chat (text model) channels share the SAME
    tools, callbacks, and flow — only the model and tone-wording differ. This is
    the seam that gives the two channels UI parity and a shared session.
    """
    return LlmAgent(
        name="upgrade_agent",
        model=model,
        description="Phone-upgrade assistant for an authorized account holder.",
        instruction=instruction,
        tools=[
            # Data tools served by the MCP server.
            McpToolset(
                connection_params=StreamableHTTPConnectionParams(url=MCP_SERVER_URL),
                tool_filter=DATA_TOOLS,
            ),
            # UI / session-control tools stay agent-local (need tool_context.state).
            FunctionTool(func=tools.render_component),
            FunctionTool(func=tools.end_call),
        ],
        before_model_callback=hide_ui_for_ivr,
        after_tool_callback=on_tool,
    )


# Voice agent (Live model). Unchanged default used by the relay + AE bidi app.
upgrade_agent = build_upgrade_agent(LIVE_MODEL)
