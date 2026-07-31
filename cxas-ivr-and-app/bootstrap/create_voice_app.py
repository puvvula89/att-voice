"""Bootstrap the CXAS app (ivr-and-app-voice) from scratch.

This is a ONE-TIME creation script: it registers the app, agents, and routing on
the platform. After it runs you `cxas pull` to get the clean declarative tree and
edit files from then on — you do not re-run this for ordinary edits.

ONE APP, BOTH MODALITIES
    There is deliberately no second app. Modality in CES is a per-TURN property of
    SessionInput, not a property of the app, so a live model serves typed turns as
    well as spoken ones. A single app also means a single session store, which is
    the whole point here: the IVR call and the in-app conversation are the same
    customer's history, reachable by the same session id.

App shape (live model):
    Voice Concierge (root, live model)
      ├─ Internet Support   (in-app)
      └─ Billing Support    (in-app)

Usage:
    python bootstrap/create_voice_app.py

Config from env (.env at the bundle root):
    GOOGLE_CLOUD_PROJECT / CXAS_PROJECT   GCP project id
    CXAS_LOCATION                         app location (default "us")
    VOICE_APP_ID                          app id (default "ivr-and-app-voice")
    VOICE_LIVE_MODEL                      live model (default "gemini-3.1-flash-live")
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
APP_ID = os.environ.get("VOICE_APP_ID", "ivr-and-app-voice")
MODEL = os.environ.get("VOICE_LIVE_MODEL", "gemini-3.1-flash-live")

APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# Agent ids.
ROOT = "voice-root"
INTERNET = "internet"
BILLING = "billing"

END_SESSION = f"{APP}/tools/end_session"  # platform built-in


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


def _existing(fn, *a, **k):
    """Create-if-missing guard: a re-run updates in place instead of failing."""
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg or "internal error" in msg or "500" in msg:
            print(f"  (create skipped: {type(e).__name__}) — will update in place")
            return None
        raise



def main():
    print(f"project={PROJECT} location={LOCATION} model={MODEL}\napp={APP}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    ag = Agents(app_name=APP)

    # 1) App. The app carries its own model_settings.model, and every agent's
    #    model must be compatible with it (the live model is a distinct modality
    #    from the default text model), so set the app model to the live model at
    #    creation time. (Updating model_settings on an app that has no root agent
    #    yet fails validation, so it must be set on create.)
    print(f"\n[1] App {APP_ID} (model={MODEL})")
    _existing(apps.create_app, app_id=APP_ID, display_name="IVR and App Voice",
              model_settings=T.ModelSettings(model=MODEL))

    # 2) Internet Support leaf.
    print("\n[2] Internet Support")
    _existing(ag.create_agent, agent_id=INTERNET, display_name="Internet Support",
              instruction=INTERNET_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(INTERNET),
                    instruction=INTERNET_INSTRUCTION, tools=[END_SESSION])
    print("   ->", agent_name(INTERNET))

    # 3) Billing Support leaf.
    print("\n[3] Billing Support")
    _existing(ag.create_agent, agent_id=BILLING, display_name="Billing Support",
              instruction=BILLING_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(BILLING),
                    instruction=BILLING_INSTRUCTION, tools=[END_SESSION])
    print("   ->", agent_name(BILLING))

    # 4) Voice Concierge — root, parent of both specialists. Routing is
    #    instruction driven ({@AGENT: Display Name}); child_agents declares reach.
    print("\n[4] Voice Concierge (root)")
    children = [agent_name(INTERNET), agent_name(BILLING)]
    _existing(ag.create_agent, agent_id=ROOT, display_name="Voice Concierge",
              instruction=ROOT_INSTRUCTION, model=MODEL,
              child_agents=children, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(ROOT), instruction=ROOT_INSTRUCTION,
                    child_agents=children, tools=[END_SESSION], transfer_rules=[])
    print("   ->", agent_name(ROOT))

    # 5) Point the app root at the Voice Concierge.
    print("\n[5] Set app root -> Voice Concierge")
    apps.update_app(app_name=APP, root_agent=agent_name(ROOT))
    print("   root set")

    print("\nDONE. Tree:")
    print("  Voice Concierge (root, live)")
    print("    ├─ Internet Support")
    print("    └─ Billing Support")
    print(f"\nNext: cxas pull \"{APP_ID}\" --project_id {PROJECT} --location {LOCATION}")


if __name__ == "__main__":
    main()
