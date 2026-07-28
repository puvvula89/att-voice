"""Attach hydration to the root agent: toolset + the before_model callback.

    python bootstrap/attach_hydration.py

Two things get attached, and the split between them is the whole design:

  * the OpenAPI toolset — the tool the platform can execute (toolsets go in the
    Agent's dedicated `toolsets` field as AgentToolset entries, NOT by dropping a
    resource name into `tools`; wrong placement fails silently);

  * a before_model callback that FIRES that tool deterministically — once per
    conversation, at the first model step, and only when the `customer_id`
    session variable holds a value.

The root instruction no longer contains a "load_context" subtask. Asking the LLM
to call a tool exactly once is a soft guarantee in both directions (it can skip
the call on turn 1 and re-call it on turn 5). The callback owns firing; the
instruction only describes how to GREET given what came back. See
steering/hydration_callback.py for the mechanism and its three locks.

Idempotent: re-running rewrites the instruction, tools, toolsets and callback.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "steering"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core import agents as agents_mod
from cxas_scrapi.core.agents import Agents

from hydration_callback import BEFORE_MODEL_CALLBACK_CODE

AgentToolset = agents_mod.types.Agent.AgentToolset

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

ROOT = "voice-root"
ROOT_NAME = f"{APP}/agents/{ROOT}"
HYDRATION_TOOLSET = f"{APP}/toolsets/hydration"
END_SESSION = f"{APP}/tools/end_session"

# The instruction describes GREETING ONLY. It deliberately says nothing about
# calling the hydration tool — by the time the model runs, the tool has either
# already returned or been hidden from its schema entirely.
ROOT_INSTRUCTION = """<role>
You are the Voice Concierge — the single entry point for every customer. You greet
once, then route to the right specialist. You never answer the request yourself.
</role>
<persona>Warm, brief, natural to listen to. Short spoken replies — no lists,
no markdown.</persona>
<taskflow>
  <subtask name="greeting_returning">
    <trigger>This is your VERY FIRST reply in the conversation AND you were given
    prior context with found=true</trigger>
    <step>Welcome them back in ONE short line. If `topic` names a real problem
    (internet, a bill, a device), ask whether they are calling about it — e.g.
    "Welcome back! Are you calling about your internet issue from earlier?"</step>
    <step>If `topic` is empty, a greeting, or too vague to name a problem, do NOT
    repeat it back — say only "Welcome back! How can I help you today?" Never
    produce a phrase like "your previous hello".</step>
    <step>Use `summary` as background so you can continue naturally, but do NOT
    read it out. Never mention how you know. Then stop and wait.</step>
  </subtask>

  <subtask name="greeting_new">
    <trigger>This is your VERY FIRST reply in the conversation AND you have no
    prior context, or it came back with found=false</trigger>
    <step>Say EXACTLY this one line and nothing else: "Thanks for calling! How can
    I help you today?"</step>
    <step>Never mention prior conversations or history. Then stop and wait.</step>
  </subtask>

  <subtask name="already_greeted">
    <trigger>You have ALREADY greeted this customer, whatever they say next</trigger>
    <step>NEVER greet again. No "Thanks for calling", no "Welcome back" — greeting
    a second time makes it sound like the conversation restarted.</step>
    <step>If what they said is not a topic you can route (a name, small talk, or
    something unclear), ask ONE short question to find out what they need help
    with — for example: "Happy to help — what can I get sorted for you?"</step>
  </subtask>

  <subtask name="route_internet">
    <trigger>The customer mentions internet, Wi-Fi, connectivity, an outage, slow
    or dropped connection, or data service</trigger>
    <step>SILENTLY transfer to {@AGENT: Internet Support}. Do not greet again or
    restate their request — just transfer.</step>
  </subtask>
  <subtask name="route_billing">
    <trigger>The customer mentions a bill, payment, a charge, their balance, a
    refund, or account/plan cost</trigger>
    <step>SILENTLY transfer to {@AGENT: Billing Support}.</step>
  </subtask>
  <subtask name="route_troubleshooting">
    <trigger>The customer mentions a device that is not working, is slow or
    erroring, needs a software or system update, or needs setup help</trigger>
    <step>SILENTLY transfer to {@AGENT: Troubleshooting Specialist}.</step>
  </subtask>
</taskflow>
"""

CALLBACK_DESCRIPTION = (
    "Fires hydration_load_prior_conversation exactly once per conversation, at "
    "the first model step, and only when the customer_id session variable is "
    "non-empty. Hides the tool from the model once hydration is settled."
)


def main():
    ag = Agents(app_name=APP)
    print(f"app={APP_ID}\nagent={ROOT}")

    print("\n[1] Attach toolset + before_model callback + greeting-only instruction")
    ag.update_agent(
        agent_name=ROOT_NAME,
        instruction=ROOT_INSTRUCTION,
        tools=[END_SESSION],
        toolsets=[AgentToolset(toolset=HYDRATION_TOOLSET,
                               tool_ids=["load_prior_conversation"])],
        before_model_callbacks=[
            T.Callback(
                python_code=BEFORE_MODEL_CALLBACK_CODE,
                description=CALLBACK_DESCRIPTION,
            )
        ],
    )
    print("   done — hydration now fires deterministically, gated on customer_id")

    print("\nNEXT")
    print("  Test: set the customer_id and resume_conversation_id variables, then")
    print("  cut a NEW version and repoint the GTP channel — channels are pinned,")
    print("  so editing the draft alone changes nothing for a live call.")


if __name__ == "__main__":
    main()
