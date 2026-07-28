"""Bootstrap the CXAS CHAT app (cxas-chat) from scratch.

This is a ONE-TIME creation script. It registers the app, its agents, and the
routing on the platform so the resources exist and get resource IDs. After it
runs successfully you `cxas pull` the app to materialise the clean declarative
tree (app.json / agents/<name>/instruction.txt + <name>.json / tools/...), and
from then on you edit those files and `cxas lint` / `cxas push`. You do not run
this script again for ordinary edits.

App shape:
    Chat Concierge (root, flash model)
      └─ Troubleshooting (basic device software-update steps)

This chat app is also the target the voice app's `a2a-to-cxas-chat` sub-agent
reaches over A2A: once deployed, its native A2A endpoint
(`.../reasoningEngines/{id}/a2a`) is the URL you feed to create_voice_app.py.

Config from env (.env at the bundle root):
    GOOGLE_CLOUD_PROJECT / CXAS_PROJECT   GCP project id
    CXAS_LOCATION                         app location (default "us")
    CHAT_APP_ID                           app id (default "cxas-chat")
    CHAT_MODEL                            flash model (default "gemini-3.5-flash")
"""
import os

from dotenv import load_dotenv

# Load the bundle-level .env (this file lives in cxas-to-cxas-a2a/bootstrap/).
load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("CHAT_APP_ID", "cxas-chat")
MODEL = os.environ.get("CHAT_MODEL", "gemini-3.5-flash")

APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# Agent ids.
ROOT = "chat-root"
TROUBLESHOOTING = "troubleshooting"

END_SESSION = f"{APP}/tools/end_session"  # platform built-in


def agent_name(aid):
    return f"{APP}/agents/{aid}"


# --- Instructions -----------------------------------------------------------

ROOT_INSTRUCTION = """<role>
You are the Chat Concierge — the single text entry point for this support app.
You do not answer questions yourself. You read the customer's first message and
route them to the specialist that handles it.
</role>
<persona>Clear, concise, friendly. Plain text replies suitable for a chat window.</persona>
<taskflow>
  <subtask name="troubleshooting">
    <trigger>The customer needs help with a device that is not working, a software
    or system update, setup, an error message, or general troubleshooting</trigger>
    <step>Transfer the conversation to {@AGENT: Troubleshooting}.</step>
  </subtask>
  <subtask name="end_conversation">
    <trigger>The customer says goodbye or indicates they are done</trigger>
    <step>Thank them and call {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""

TROUBLESHOOTING_INSTRUCTION = """<role>
You are the Troubleshooting specialist. You help customers resolve basic device
problems, with a focus on keeping the device software up to date.
</role>
<persona>Patient and clear. Give one step at a time and confirm the result before
moving on. Plain text, short numbered steps.</persona>
<taskflow>
  <subtask name="software_update">
    <trigger>The customer has a device that is misbehaving, slow, or asks how to
    update their device software</trigger>
    <step>Confirm the device type (phone, tablet) and its operating system if
    unknown.</step>
    <step>Walk them through checking for a software update, one step at a time:
      1. Make sure the device is connected to Wi-Fi and charged above 50%.
      2. Open Settings.
      3. Go to the System (or General) section.
      4. Open "Software update" (or "System update").
      5. Tap "Check for updates" and, if one is offered, "Download and install".
      6. Let the device restart and finish installing.</step>
    <step>After the update, ask whether the original problem is resolved.</step>
  </subtask>
  <subtask name="still_broken">
    <trigger>The problem persists after updating</trigger>
    <step>Have them restart the device once more, then confirm the symptom again.</step>
    <step>If it still fails, tell them it may need deeper support and summarise what
    they have already tried.</step>
  </subtask>
  <subtask name="end_conversation">
    <trigger>The customer is satisfied or says they are done</trigger>
    <step>Thank them and call {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""


def _existing(fn, *a, **k):
    """Create-if-missing guard. Tolerates ALREADY_EXISTS and the 500 the server
    returns on a duplicate create; the following update_agent is the real write."""
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

    # 1) App. Set the app-level model at creation time so it matches the agents'
    #    model (agent models must be compatible with the app's model_settings.model;
    #    updating model_settings before a root agent exists fails validation).
    print(f"\n[1] App {APP_ID} (model={MODEL})")
    _existing(apps.create_app, app_id=APP_ID, display_name="CXAS Chat",
              model_settings=T.ModelSettings(model=MODEL))

    # 2) Troubleshooting leaf.
    print("\n[2] Troubleshooting")
    _existing(ag.create_agent, agent_id=TROUBLESHOOTING, display_name="Troubleshooting",
              instruction=TROUBLESHOOTING_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(TROUBLESHOOTING),
                    instruction=TROUBLESHOOTING_INSTRUCTION, tools=[END_SESSION])
    print("   ->", agent_name(TROUBLESHOOTING))

    # 3) Chat Concierge — root, parent of Troubleshooting. Routing is instruction
    #    driven ({@AGENT: Display Name}); child_agents declares reachability.
    print("\n[3] Chat Concierge (root)")
    _existing(ag.create_agent, agent_id=ROOT, display_name="Chat Concierge",
              instruction=ROOT_INSTRUCTION, model=MODEL,
              child_agents=[agent_name(TROUBLESHOOTING)], tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(ROOT), instruction=ROOT_INSTRUCTION,
                    child_agents=[agent_name(TROUBLESHOOTING)], tools=[END_SESSION],
                    transfer_rules=[])
    print("   ->", agent_name(ROOT))

    # 4) Point the app root at the Chat Concierge.
    print("\n[4] Set app root -> Chat Concierge")
    apps.update_app(app_name=APP, root_agent=agent_name(ROOT))
    print("   root set")

    print("\nDONE. Tree:")
    print("  Chat Concierge (root)")
    print("    └─ Troubleshooting")
    print(f"\nNext: cxas pull \"{APP_ID}\" --project_id {PROJECT} --location {LOCATION}")


if __name__ == "__main__":
    main()
