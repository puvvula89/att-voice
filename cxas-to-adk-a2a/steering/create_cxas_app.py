"""Create the CXAS app and the `sales-adapter` A2A RemoteAgentTool from scratch.

A2A variant. This is the FIRST CXAS step in a clean-slate deploy (before
create_steering_tree.py and apply_sales_callbacks.py):
  1. create the app named by CXAS_APP_ID (idempotent — tolerates ALREADY_EXISTS)
  2. create the `sales-adapter` A2A RemoteAgentTool pointing at the chat Agent
     Engine's native A2A endpoint. No OpenAPI schema, no OIDC config: CES reaches
     the Agent Engine endpoint using its P4SA (per-project service agent) by
     default for internal GCP auth, so RemoteAgentTool carries no auth field.

The tool's AgentCard interface URL is the Agent Engine A2A endpoint
(`…/reasoningEngines/{id}/a2a`), passed as the single argument.

Usage: python steering/create_cxas_app.py <AGENT_ENGINE_A2A_URL>
Config from env: CXAS_PROJECT, CXAS_LOCATION, CXAS_APP_ID.
"""
import os
import sys

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("CXAS_APP_ID", "att-ivr-steering-a2a")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
TOOL_ID = "sales-adapter"
TOOL = f"{APP}/tools/{TOOL_ID}"

# A2A protocol version the Agent Engine endpoint exposes (matches the installed
# a2a-sdk's PROTOCOL_VERSION_CURRENT and the card the A2aAgent template publishes).
A2A_PROTOCOL_VERSION = "1.0"

# Routing description — mirrors the old OpenAPI operation summary so the Telephony
# Sales Master treats the A2A tool exactly like the previous HTTP tool.
_TOOL_DESCRIPTION = (
    "Reach the AT&T sales specialist for ANY device upgrade, phone, plan, line, "
    "trade-in, price, or order request. REQUIRED for every device or sales turn. "
    "The Telephony Sales Master is only a router and has NO product knowledge of its "
    "own — the specialist reached through this tool owns the phone catalog, pricing, "
    "eligibility, trade-in values, and order placement. Call this tool on EVERY turn "
    "where the caller talks about a device, upgrade, phone, plan, line, trade-in, "
    "price, or placing/confirming an order — including the very first thing they say "
    "after being routed here. Speak the returned reply verbatim. Never answer these "
    "from your own knowledge and never invent lines, prices, eligibility, or "
    "confirmations. Only skip this tool for a pure greeting or when closing the call."
)


def _tolerate_exists(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg:
            print(f"  (already exists) {type(e).__name__}")
            return None
        raise


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: create_cxas_app.py <AGENT_ENGINE_A2A_URL>")
    a2a_url = sys.argv[1].rstrip("/")
    print(f"project={PROJECT} location={LOCATION}\napp={APP}\na2a_endpoint={a2a_url}")

    # 1) App.
    print(f"\n[1] App {APP_ID}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    _tolerate_exists(apps.create_app, app_id=APP_ID, display_name="AT&T IVR Steering")

    # 2) sales-adapter A2A RemoteAgentTool. Skipped when SALES_TOOL_ENABLED=false
    #    (the CES create API currently rejects RemoteAgentTool). Skipping lets the
    #    rest of the deploy (tree + callbacks) build the full hierarchy without it.
    if os.environ.get("SALES_TOOL_ENABLED", "true").lower() in ("false", "0", "no"):
        print("\n[2] Tool sales-adapter — SKIPPED (SALES_TOOL_ENABLED=false)")
        return

    print("\n[2] Tool sales-adapter (A2A RemoteAgentTool, P4SA auth)")
    client = Agents(app_name=APP).client
    try:
        client.delete_tool(request=T.DeleteToolRequest(name=TOOL))
        print("   (removed pre-existing tool)")
    except Exception:
        pass

    tool = T.Tool(
        display_name="sales_adapter",
        execution_type=T.ExecutionType.SYNCHRONOUS,  # ASYNCHRONOUS later, for the filler
        remote_agent_tool=T.RemoteAgentTool(
            name="call_sales_specialist",
            description=_TOOL_DESCRIPTION,
            agent_card=T.AgentCard(
                name="AT&T Telephony Sales Specialist",
                description="Voice-tuned AT&T phone-upgrade sales agent over A2A.",
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
                        id="call_sales_specialist",
                        name="AT&T Sales Specialist",
                        description=_TOOL_DESCRIPTION,
                        tags=["sales", "device", "upgrade", "plan", "trade-in", "order"],
                        examples=[
                            "I want to upgrade my phone",
                            "what plans do you have",
                            "trade in my old phone",
                        ],
                    )
                ],
            ),
        ),
    )
    try:
        created = client.create_tool(
            request=T.CreateToolRequest(parent=APP, tool_id=TOOL_ID, tool=tool)
        )
        print("   created:", created.name, f"(A2A -> {a2a_url}, P4SA)")
    except Exception as e:
        # The CES create API may reject RemoteAgentTool ("not supported"). Don't abort
        # the deploy — warn and continue so the hierarchy still builds. Create the tool
        # in the console when available, then re-run with SALES_TOOL_ENABLED=true.
        if "not supported" in str(e).lower():
            print("   ⚠ RemoteAgentTool creation not supported by this CES env — "
                  "skipping tool (create it in the console, then re-run the tree).")
        else:
            raise


if __name__ == "__main__":
    main()
