"""Author the CXAS steering tree that matches the corrected architecture:

    Global Concierge Steering (root)
      └─ Consumer Steering
           ├─ Telephony Sales Master ──sales-adapter toolset──▶ ADK root
           └─ Care Agents (stub)

CXAS always enters ADK at its ROOT via the `sales-adapter` OpenAPI toolset;
ADK owns its own internal routing (Internet / Wireless). CXAS never calls an
ADK sub-agent directly.

Reuses the app named by CXAS_APP_ID and its `sales-adapter` A2A tool.
Repurposes the existing `telephony-steering` agent as the Telephony Sales Master
leaf. Idempotent-ish: create calls tolerate ALREADY_EXISTS.

Config from env: CXAS_PROJECT, CXAS_LOCATION, CXAS_APP_ID, CXAS_MODEL.
"""
import os

from cxas_scrapi.core import agents as agents_mod
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.variables import Variables, VariableType

types = agents_mod.types

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
MODEL = os.environ.get("CXAS_MODEL", "gemini-2.5-flash-001")

APP_ID = os.environ.get("CXAS_APP_ID", "att-ivr-steering-a2a")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# Session variable that identifies the caller. The Sales Master passes this as the
# tool's customer_id, which the adapter maps verbatim to the ADK user_id (the
# cross-channel session anchor). Default "wilson" so the telephony path (no
# override) resolves to wilson; override per session via Sessions.run(variables=
# {"customer_id": "..."}) or a session parameter in the UI to swap users.
CUSTOMER_ID_VAR = "customer_id"
CUSTOMER_ID_DEFAULT = os.environ.get("CXAS_CUSTOMER_ID_DEFAULT", "wilson")

# Agent ids.
CONCIERGE = "global-concierge"
CONSUMER = "consumer-steering"
SALES = "telephony-steering"        # reused as Telephony Sales Master
CARE = "care-agents"

def agent_name(aid):
    return f"{APP}/agents/{aid}"

# A2A variant: the sales specialist is a standalone RemoteAgentTool (not an OpenAPI
# toolset), attached to the agent the same way end_session is. Its qualified name
# stays `sales_adapter_call_sales_specialist` (display_name `sales_adapter` + tool
# name `call_sales_specialist`) so the {@TOOL} macros and the before/after_tool
# session-threading callbacks keep matching.
SALES_TOOL = f"{APP}/tools/sales-adapter"
END_SESSION = f"{APP}/tools/end_session"

# The A2A RemoteAgentTool is not yet creatable in this CES environment (the create
# API rejects it). Set SALES_TOOL_ENABLED=false to build the full agent hierarchy
# WITHOUT the sales tool: the Sales Master is created with only end_session and its
# instruction's sales-tool macro is neutralized so CES doesn't reject a dangling
# {@TOOL} reference. Flip back to true once the tool exists to wire in delegation.
SALES_TOOL_ENABLED = os.environ.get("SALES_TOOL_ENABLED", "true").lower() not in ("false", "0", "no")
_SALES_TOOL_MACRO = "{@TOOL: sales_adapter_call_sales_specialist}"

# --- Instructions -----------------------------------------------------------

CONCIERGE_INSTRUCTION = """<role>
You are the AT&T Global Concierge — the single voice entry point for every caller.
Greet the caller ONCE, then hand the call to the Consumer Steering agent to route
them. You never answer sales or care questions yourself.
</role>
<persona>Warm, brief, natural to listen to. Short spoken replies — no lists,
no markdown.</persona>
<taskflow>
  <subtask name="greeting">
    <trigger>The call starts</trigger>
    <step>Say EXACTLY this one line and nothing else: "Thank you for calling AT&T!
    How can I help you today?"</step>
    <step>Say it only ONCE. Do NOT repeat any part of it. Do NOT introduce yourself,
    do NOT say the word "concierge", and do NOT name any AT&T team or agent. After
    saying the line, stop talking and wait for the caller.</step>
  </subtask>
  <subtask name="steer">
    <trigger>The caller states what they need</trigger>
    <step>SILENTLY transfer the call to {@AGENT: Consumer Steering} so it can route
    to the right specialist. Do NOT greet again, do NOT re-ask how you can help, do
    NOT acknowledge or restate their request, and do NOT try to answer it yourself —
    just transfer.</step>
  </subtask>
</taskflow>
"""

CONSUMER_INSTRUCTION = """<role>
You are the AT&T Consumer Steering agent. You decide which specialist handles the
caller and transfer them there. You do not answer the request yourself.
</role>
<persona>Warm, brief, natural. Short spoken replies.</persona>
<taskflow>
  <subtask name="sales">
    <trigger>The caller wants to upgrade a device, buy a phone, or asks about
    sales, plans, or trade-in</trigger>
    <step>Transfer the call to {@AGENT: Telephony Sales Master}.</step>
  </subtask>
  <subtask name="care">
    <trigger>The caller wants billing, technical support, or account help</trigger>
    <step>Transfer the call to {@AGENT: Care Agents}.</step>
  </subtask>
</taskflow>
"""

SALES_INSTRUCTION = """<role>
  You are the AT&T Telephony Sales Master. You have NO product knowledge of your own.
  You handle device upgrades, new phones, plans, lines, trade-in, and orders ONLY by
  delegating to the ADK sales specialist via {@TOOL: sales_adapter_call_sales_specialist}.
</role>

<persona>
  Warm, brief, and natural to listen to. Short spoken replies — no lists, no markdown.
  Do NOT greet the caller; they have already been greeted. Respond directly.
</persona>

<taskflow>

  <subtask name="handle_sales">
    <trigger>
      The caller says ANYTHING about a device, upgrade, phone, plan, line, trade-in,
      price, or placing/confirming an order — including their first words to you.
    </trigger>
    <step>
      You CANNOT answer these yourself. Call {@TOOL: sales_adapter_call_sales_specialist}
      with:
        - customer_id             = "{customer_id}"  (ALWAYS this exact value; never change it)
        - utterance               = the caller's exact words
        - caller_sentiment_label  = the caller's tone this turn: calm, neutral, annoyed, frustrated, or angry
        - caller_sentiment_score  = frustration intensity from 0.0 (calm) to 1.0 (furious)
    </step>
    <step>
      Say the returned reply to the caller, verbatim and naturally — add no words of
      your own before or after it.
    </step>
    <rule>
      Never answer from your own knowledge. Never invent lines, prices, eligibility,
      or order confirmations.
    </rule>
  </subtask>

  <subtask name="close_call">
    <trigger>
      The caller indicates they are finished (e.g. "no", "nothing else", "that's all",
      "that's it", "I'm good", "we're done", "goodbye").
    </trigger>
    <step>Do NOT call the sales tool — there is nothing to delegate.</step>
    <step>
      In ONE turn, SPEAK exactly "Thank you for contacting AT&T. Have a great day!"
      and call {@TOOL: end_session}. Say the line once; never end the call silently.
    </step>
  </subtask>

</taskflow>
"""

CARE_INSTRUCTION = """<role>
You are the AT&T Care Agents front door (a stub in this POC). You handle billing,
technical support, and account help.
</role>
<persona>Warm, brief, natural. Short spoken replies.</persona>
<taskflow>
  <subtask name="care">
    <trigger>The caller needs billing, support, or account help</trigger>
    <step>Tell the caller you will connect them to customer care. (Care routing is
    a stub in this POC.)</step>
    <step>If they are done, call {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""


def _existing(fn, *a, **k):
    """Create-if-missing guard. Tolerates ALREADY_EXISTS; also tolerates the 500
    the server returns when creating a duplicate agent (the following update_agent
    is the real write, and will surface a genuine 404 on a fresh deploy)."""
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg or "internal error" in msg or "500" in msg:
            print(f"  (create skipped: {type(e).__name__}) — will update in place")
            return None
        raise


def main():
    print(f"Project={PROJECT} location={LOCATION} model={MODEL}\napp={APP}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    ag = Agents(app_name=APP)

    # 0) Declare the customer_id session variable (default identity). Idempotent:
    #    create_variable no-ops if it already exists.
    print(f"\n[0] Session variable {CUSTOMER_ID_VAR} (default '{CUSTOMER_ID_DEFAULT}')")
    Variables(app_name=APP).create_variable(
        variable_name=CUSTOMER_ID_VAR,
        variable_type=VariableType.STRING,
        variable_value=CUSTOMER_ID_DEFAULT,
    )

    # 1) Telephony Sales Master: create if missing (fresh app), then set the
    #    sales-only instruction. Attach the sales-adapter A2A tool + end_session when
    #    SALES_TOOL_ENABLED; otherwise attach only end_session and neutralize the
    #    dangling sales-tool macro so the hierarchy still builds.
    print("\n[1] Telephony Sales Master")
    if SALES_TOOL_ENABLED:
        sales_tools = [END_SESSION, SALES_TOOL]
        sales_instruction = SALES_INSTRUCTION
    else:
        sales_tools = [END_SESSION]
        sales_instruction = SALES_INSTRUCTION.replace(
            _SALES_TOOL_MACRO, "the ADK sales specialist (A2A tool pending enablement)"
        )
        print("   (SALES_TOOL_ENABLED=false — building Sales Master WITHOUT the A2A tool)")
    _existing(ag.create_agent, agent_id=SALES, display_name="Telephony Sales Master",
              instruction=sales_instruction, model=MODEL, tools=[END_SESSION])
    ag.update_agent(
        agent_name=agent_name(SALES),
        display_name="Telephony Sales Master",
        instruction=sales_instruction,
        tools=sales_tools,
    )
    print("   ready:", agent_name(SALES))

    # Routing is INSTRUCTION-driven: child_agents declares the reachable children;
    # each parent's instruction transfers by direct {@AGENT: Display Name} reference
    # based on intent. We deliberately set NO transfer_rules (handoff rules) — those
    # are an OPTIONAL deterministic overlay (condition/Python based). Leaving them
    # empty just showed a confusing blank "Handoff rules (1)" in the console, so we
    # clear them (transfer_rules=[]) and rely on the instructions.

    # 2) Care Agents leaf.
    print("\n[2] Care Agents")
    _existing(ag.create_agent, agent_id=CARE, display_name="Care Agents",
              instruction=CARE_INSTRUCTION, model=MODEL, tools=[END_SESSION])
    ag.update_agent(agent_name=agent_name(CARE), instruction=CARE_INSTRUCTION)
    print("   ->", agent_name(CARE))

    # 3) Consumer Steering — parent of Sales Master + Care (child_agents only).
    print("\n[3] Consumer Steering")
    _existing(
        ag.create_agent, agent_id=CONSUMER, display_name="Consumer Steering",
        instruction=CONSUMER_INSTRUCTION, model=MODEL,
        child_agents=[agent_name(SALES), agent_name(CARE)],
    )
    ag.update_agent(
        agent_name=agent_name(CONSUMER),
        instruction=CONSUMER_INSTRUCTION,
        child_agents=[agent_name(SALES), agent_name(CARE)],
        transfer_rules=[],   # clear any empty handoff rules
    )
    print("   ->", agent_name(CONSUMER))

    # 4) Global Concierge — root, parent of Consumer Steering (child_agents only).
    print("\n[4] Global Concierge Steering")
    _existing(
        ag.create_agent, agent_id=CONCIERGE,
        display_name="Global Concierge Steering",
        instruction=CONCIERGE_INSTRUCTION, model=MODEL,
        child_agents=[agent_name(CONSUMER)],
    )
    ag.update_agent(
        agent_name=agent_name(CONCIERGE),
        instruction=CONCIERGE_INSTRUCTION,
        child_agents=[agent_name(CONSUMER)],
        transfer_rules=[],   # clear any empty handoff rules
    )
    print("   ->", agent_name(CONCIERGE))

    # 5) Point the app root at the Global Concierge.
    print("\n[5] Set app root -> Global Concierge")
    apps.update_app(app_name=APP, root_agent=agent_name(CONCIERGE))
    print("   root set")

    print("\nDONE. Tree:")
    print("  Global Concierge Steering (root)")
    print("    └─ Consumer Steering")
    print("         ├─ Telephony Sales Master ──sales-adapter──▶ ADK root")
    print("         └─ Care Agents (stub)")


if __name__ == "__main__":
    main()
