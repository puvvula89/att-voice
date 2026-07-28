"""Bootstrap the CXAS VOICE app (cxas-voice-and-chat) from scratch.

This is a ONE-TIME creation script (same model as create_chat_app.py): it
registers the app, agents, routing, and the A2A tool on the platform. After it
runs you `cxas pull` to get the clean declarative tree and edit files from then
on — you do not re-run this for ordinary edits.

App shape (voice / live model):
    Voice Concierge (root, live model)
      ├─ Internet Support        (voice, in-app)
      ├─ Billing Support         (voice, in-app)
      └─ Troubleshooting Specialist  == the `a2a-to-cxas-chat` sub-agent:
             forwards troubleshooting turns over A2A to the separate cxas-chat
             app via the `chat_adapter` RemoteAgentTool, and speaks the reply back.

The A2A hop is intentionally a thin wrapper. This script creates the
`chat_adapter` RemoteAgentTool pointing at the deployed cxas-chat app's native
A2A endpoint (`.../reasoningEngines/{id}/a2a`). Because some CES environments
reject RemoteAgentTool creation, the tool is gated by CHAT_TOOL_ENABLED: when
disabled the full hierarchy still builds, the wrapper carries only end_session,
and its tool macro is neutralised so no dangling {@TOOL} reference is pushed.
Wire the real plumbing (endpoint URL + P4SA auth) later, then re-run with
CHAT_TOOL_ENABLED=true.

Usage:
    python bootstrap/create_voice_app.py [CHAT_A2A_URL]
    # CHAT_A2A_URL may also come from the CHAT_A2A_URL env var.

Config from env (.env at the bundle root):
    GOOGLE_CLOUD_PROJECT / CXAS_PROJECT   GCP project id
    CXAS_LOCATION                         app location (default "us")
    VOICE_APP_ID                          app id (default "cxas-voice-and-chat")
    VOICE_LIVE_MODEL                      live model (default "gemini-3.1-flash-live")
    CHAT_TOOL_ENABLED                     create the A2A tool (default "false")
    CHAT_A2A_URL                          deployed cxas-chat A2A endpoint URL
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
MODEL = os.environ.get("VOICE_LIVE_MODEL", "gemini-3.1-flash-live")

APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# A2A protocol version the cxas-chat A2A endpoint exposes.
A2A_PROTOCOL_VERSION = "1.0"

# Agent ids.
ROOT = "voice-root"
INTERNET = "internet"
BILLING = "billing"
CHAT_WRAPPER = "a2a-to-cxas-chat"

# The A2A tool: display_name `chat_adapter` + remote name `call_chat_specialist`
# → qualified tool name `chat_adapter_call_chat_specialist` (this is the string
# the {@TOOL} macro must reference).
CHAT_TOOL_ID = "chat-adapter"
CHAT_TOOL = f"{APP}/tools/{CHAT_TOOL_ID}"
CHAT_TOOL_MACRO = "{@TOOL: chat_adapter_call_chat_specialist}"
END_SESSION = f"{APP}/tools/end_session"  # platform built-in

CHAT_TOOL_ENABLED = os.environ.get("CHAT_TOOL_ENABLED", "false").lower() not in ("false", "0", "no")

_CHAT_TOOL_DESCRIPTION = (
    "Reach the troubleshooting specialist for ANY device-troubleshooting request: "
    "a device that will not work, is slow or erroring, needs a software or system "
    "update, or needs setup help. The Troubleshooting Specialist here is only a "
    "relay and has NO troubleshooting knowledge of its own — the specialist reached "
    "through this tool (a separate chat app) owns the actual troubleshooting steps. "
    "Call this tool on every troubleshooting turn, pass the caller's exact words, and "
    "speak the returned reply back verbatim. Never invent troubleshooting steps."
)


def agent_name(aid):
    return f"{APP}/agents/{aid}"


# --- Instructions -----------------------------------------------------------

ROOT_INSTRUCTION = """<role>
You are the Voice Concierge — the single voice entry point for every caller.
Greet the caller ONCE, then route them to the right specialist based on what they
need. You never answer the request yourself.
</role>
<persona>Warm, brief, natural to listen to. Short spoken replies — no lists,
no markdown.</persona>
<taskflow>
  <subtask name="greeting">
    <trigger>The call starts</trigger>
    <step>Say EXACTLY this one line and nothing else: "Thanks for calling! How can I
    help you today?"</step>
    <step>Say it only ONCE. Do not repeat it, do not introduce yourself, do not name
    any team or agent. Then stop and wait for the caller.</step>
  </subtask>
  <subtask name="route_internet">
    <trigger>The caller mentions internet, Wi-Fi, connectivity, an outage, slow or
    dropped connection, or data service</trigger>
    <step>SILENTLY transfer the call to {@AGENT: Internet Support}. Do not greet
    again or restate their request — just transfer.</step>
  </subtask>
  <subtask name="route_billing">
    <trigger>The caller mentions a bill, payment, a charge, their balance, a refund,
    or account/plan cost</trigger>
    <step>SILENTLY transfer the call to {@AGENT: Billing Support}. Do not greet
    again or restate their request — just transfer.</step>
  </subtask>
  <subtask name="route_troubleshooting">
    <trigger>The caller mentions a device that is not working, is slow or erroring,
    needs a software or system update, or needs setup help</trigger>
    <step>SILENTLY transfer the call to {@AGENT: Troubleshooting Specialist}. Do not
    greet again or restate their request — just transfer.</step>
  </subtask>
</taskflow>
"""

INTERNET_INSTRUCTION = """<role>
You are Internet Support (voice). You help callers with internet and connectivity:
Wi-Fi issues, outages, slow or dropped connections, and data service questions.
</role>
<persona>Warm, brief, natural. Short spoken replies. Do NOT greet — the caller has
already been greeted. Respond directly.</persona>
<taskflow>
  <subtask name="help_internet">
    <trigger>The caller describes an internet or connectivity problem</trigger>
    <step>Ask one brief clarifying question if you need it, then give simple spoken
    guidance (for example: check the modem lights, restart the router, confirm the
    outage status in their area).</step>
    <step>Confirm whether that resolved it.</step>
  </subtask>
  <subtask name="close_call">
    <trigger>The caller is done</trigger>
    <step>In ONE turn, say "Thanks for calling. Have a great day!" and call
    {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""

BILLING_INSTRUCTION = """<role>
You are Billing Support (voice). You help callers with billing questions: charges,
payments, balances, refunds, and plan costs.
</role>
<persona>Warm, brief, natural. Short spoken replies. Do NOT greet — the caller has
already been greeted. Respond directly.</persona>
<taskflow>
  <subtask name="help_billing">
    <trigger>The caller asks about a bill, charge, payment, balance, or refund</trigger>
    <step>Ask one brief clarifying question if needed, then give a clear spoken
    answer or next step. (Account lookups are a stub in this POC.)</step>
    <step>Confirm whether that answered their question.</step>
  </subtask>
  <subtask name="close_call">
    <trigger>The caller is done</trigger>
    <step>In ONE turn, say "Thanks for calling. Have a great day!" and call
    {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""

# The a2a-to-cxas-chat wrapper. It has NO troubleshooting knowledge; every
# troubleshooting turn is delegated to the remote cxas-chat specialist via the
# chat_adapter A2A tool, and the reply is spoken back verbatim.
CHAT_WRAPPER_INSTRUCTION = """<role>
You are the Troubleshooting Specialist front door on the voice channel. You have NO
troubleshooting knowledge of your own. You handle every troubleshooting request ONLY
by delegating to the remote troubleshooting specialist via {@TOOL: chat_adapter_call_chat_specialist}.
</role>
<persona>Warm, brief, natural to listen to. Short spoken replies — no lists, no
markdown. Do NOT greet the caller; they have already been greeted. Respond directly.</persona>
<taskflow>
  <subtask name="handle_troubleshooting">
    <trigger>The caller says ANYTHING about a device not working, a software or system
    update, an error, or setup — including their first words to you</trigger>
    <step>You CANNOT answer this yourself. Call {@TOOL: chat_adapter_call_chat_specialist}
    with the caller's exact words as the utterance.</step>
    <step>Say the returned reply to the caller, verbatim and naturally — add no words
    of your own before or after it.</step>
    <rule>Never answer from your own knowledge. Never invent troubleshooting steps.</rule>
  </subtask>
  <subtask name="close_call">
    <trigger>The caller indicates they are finished</trigger>
    <step>Do NOT call the tool — there is nothing to delegate.</step>
    <step>In ONE turn, say "Thanks for calling. Have a great day!" and call
    {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""


def _existing(fn, *a, **k):
    """Create-if-missing guard (see create_chat_app.py)."""
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg or "internal error" in msg or "500" in msg:
            print(f"  (create skipped: {type(e).__name__}) — will update in place")
            return None
        raise


def _create_chat_tool(a2a_url):
    """Create the chat_adapter A2A RemoteAgentTool pointing at the cxas-chat
    endpoint. Mirrors the P4SA (no explicit auth) pattern; tolerant of a CES env
    that does not support RemoteAgentTool creation."""
    client = Agents(app_name=APP).client
    try:
        client.delete_tool(request=T.DeleteToolRequest(name=CHAT_TOOL))
        print("   (removed pre-existing tool)")
    except Exception:
        pass

    tool = T.Tool(
        display_name="chat_adapter",
        execution_type=T.ExecutionType.SYNCHRONOUS,
        remote_agent_tool=T.RemoteAgentTool(
            name="call_chat_specialist",
            description=_CHAT_TOOL_DESCRIPTION,
            agent_card=T.AgentCard(
                name="CXAS Troubleshooting Specialist",
                description="Chat troubleshooting agent (cxas-chat) reached over A2A.",
                version="1.0.0",
                supported_interfaces=[
                    T.AgentInterface(
                        url=a2a_url,
                        protocol_binding="HTTP+JSON",
                        protocol_version=A2A_PROTOCOL_VERSION,
                    )
                ],
                skills=[
                    T.AgentSkill(
                        id="call_chat_specialist",
                        name="Troubleshooting Specialist",
                        description=_CHAT_TOOL_DESCRIPTION,
                        tags=["troubleshooting", "device", "software-update", "setup"],
                        examples=[
                            "my phone won't turn on",
                            "how do I update my device software",
                            "my tablet keeps crashing",
                        ],
                    )
                ],
            ),
        ),
    )
    try:
        created = client.create_tool(
            request=T.CreateToolRequest(parent=APP, tool_id=CHAT_TOOL_ID, tool=tool)
        )
        print("   created:", created.name, f"(A2A -> {a2a_url}, P4SA)")
        return True
    except Exception as e:
        if "not supported" in str(e).lower():
            print("   ⚠ RemoteAgentTool creation not supported by this CES env — "
                  "skipping tool (create it in the console, then re-run with "
                  "CHAT_TOOL_ENABLED=true).")
            return False
        raise


def main():
    a2a_url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHAT_A2A_URL", "")).rstrip("/")
    print(f"project={PROJECT} location={LOCATION} model={MODEL}\napp={APP}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    ag = Agents(app_name=APP)

    # 1) App. The app carries its own model_settings.model, and every agent's
    #    model must be compatible with it (the live model is a distinct modality
    #    from the default text model), so set the app model to the live model at
    #    creation time. (Updating model_settings on an app that has no root agent
    #    yet fails validation, so it must be set on create.)
    print(f"\n[1] App {APP_ID} (model={MODEL})")
    _existing(apps.create_app, app_id=APP_ID, display_name="CXAS Voice and Chat",
              model_settings=T.ModelSettings(model=MODEL))

    # 2) chat_adapter A2A tool (optional). Decides whether the wrapper delegates.
    tool_live = False
    print("\n[2] chat_adapter A2A tool")
    if not CHAT_TOOL_ENABLED:
        print("   SKIPPED (CHAT_TOOL_ENABLED=false) — wrapper will carry only end_session")
    elif not a2a_url:
        print("   ⚠ CHAT_TOOL_ENABLED=true but no CHAT_A2A_URL / argv given — skipping")
    else:
        tool_live = _create_chat_tool(a2a_url)

    if tool_live:
        wrapper_tools = [END_SESSION, CHAT_TOOL]
        wrapper_instruction = CHAT_WRAPPER_INSTRUCTION
    else:
        wrapper_tools = [END_SESSION]
        wrapper_instruction = CHAT_WRAPPER_INSTRUCTION.replace(
            CHAT_TOOL_MACRO, "the remote troubleshooting specialist (A2A tool pending)"
        )

    # 3) Internet Support leaf.
    print("\n[3] Internet Support")
    _existing(ag.create_agent, agent_id=INTERNET, display_name="Internet Support",
              instruction=INTERNET_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(INTERNET),
                    instruction=INTERNET_INSTRUCTION, tools=[END_SESSION])
    print("   ->", agent_name(INTERNET))

    # 4) Billing Support leaf.
    print("\n[4] Billing Support")
    _existing(ag.create_agent, agent_id=BILLING, display_name="Billing Support",
              instruction=BILLING_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(BILLING),
                    instruction=BILLING_INSTRUCTION, tools=[END_SESSION])
    print("   ->", agent_name(BILLING))

    # 5) a2a-to-cxas-chat wrapper (display "Troubleshooting Specialist").
    print("\n[5] Troubleshooting Specialist (a2a-to-cxas-chat)")
    _existing(ag.create_agent, agent_id=CHAT_WRAPPER, display_name="Troubleshooting Specialist",
              instruction=wrapper_instruction, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(CHAT_WRAPPER),
                    instruction=wrapper_instruction, tools=wrapper_tools)
    print("   ->", agent_name(CHAT_WRAPPER))

    # 6) Voice Concierge — root, parent of the three specialists. Routing is
    #    instruction driven ({@AGENT: Display Name}); child_agents declares reach.
    print("\n[6] Voice Concierge (root)")
    children = [agent_name(INTERNET), agent_name(BILLING), agent_name(CHAT_WRAPPER)]
    _existing(ag.create_agent, agent_id=ROOT, display_name="Voice Concierge",
              instruction=ROOT_INSTRUCTION, model=MODEL,
              child_agents=children, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(ROOT), instruction=ROOT_INSTRUCTION,
                    child_agents=children, tools=[END_SESSION], transfer_rules=[])
    print("   ->", agent_name(ROOT))

    # 7) Point the app root at the Voice Concierge.
    print("\n[7] Set app root -> Voice Concierge")
    apps.update_app(app_name=APP, root_agent=agent_name(ROOT))
    print("   root set")

    print("\nDONE. Tree:")
    print("  Voice Concierge (root, live)")
    print("    ├─ Internet Support")
    print("    ├─ Billing Support")
    print("    └─ Troubleshooting Specialist ──chat_adapter A2A──▶ cxas-chat")
    print(f"\nNext: cxas pull \"{APP_ID}\" --project_id {PROJECT} --location {LOCATION}")


if __name__ == "__main__":
    main()
