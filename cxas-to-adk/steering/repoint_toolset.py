"""Repoint the `sales-adapter` OpenAPI toolset at the dedicated adapter service and
secure it with OIDC (CES service-agent ID token).

CES does not support UpdateToolset, so this DELETES and RECREATES the toolset with
the same id (`sales-adapter`) so the agent's AgentToolset ref stays valid:
  1. detach toolset from the Telephony Sales Master agent
  2. delete the toolset (force)
  3. recreate it: OpenAPI schema servers[0].url -> new adapter, api_authentication ->
     service_agent_id_token_auth_config {} (CES SA mints the OIDC ID token)
  4. reattach to the agent

Usage: python repoint_toolset.py <ADAPTER_BASE_URL>
"""
import json
import sys

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents

APP = "projects/REDACTED_PROJECT/locations/us/apps/att-ivr-steering"
TOOLSET_ID = "sales-adapter"
TOOLSET = f"{APP}/toolsets/{TOOLSET_ID}"
SALES_AGENT = f"{APP}/agents/telephony-steering"  # Telephony Sales Master
END_SESSION = f"{APP}/tools/end_session"
OP_ID = "call_sales_specialist"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: repoint_toolset.py <ADAPTER_BASE_URL>")
    base = sys.argv[1].rstrip("/")

    agents = Agents(app_name=APP)
    client = agents.client

    # Snapshot the current toolset so we preserve schema + display_name.
    ts = client.get_toolset(name=TOOLSET)
    schema = json.loads(ts.open_api_toolset.open_api_schema)
    old = schema.get("servers", [{}])[0].get("url", "?")
    schema["servers"] = [{"url": base}]
    display = ts.display_name or "sales_adapter"
    print(f"servers url: {old}  ->  {base}")

    # 1) Detach from the Sales Master agent.
    print("[1] detach toolset from agent")
    agents.update_agent(agent_name=SALES_AGENT, toolsets=[], tools=[END_SESSION])

    # 2) Delete the old toolset.
    print("[2] delete old toolset")
    client.delete_toolset(request=T.DeleteToolsetRequest(name=TOOLSET, force=True))

    # 3) Recreate with new URL + OIDC auth.
    print("[3] recreate toolset with new URL + OIDC")
    new_ts = T.Toolset(
        display_name=display,
        open_api_toolset=T.OpenApiToolset(
            open_api_schema=json.dumps(schema),
            api_authentication=T.ApiAuthentication(
                service_agent_id_token_auth_config=T.ServiceAgentIdTokenAuthConfig()
            ),
        ),
    )
    created = client.create_toolset(
        request=T.CreateToolsetRequest(parent=APP, toolset_id=TOOLSET_ID, toolset=new_ts)
    )
    print("   created:", created.name)
    print("   auth:", created.open_api_toolset.api_authentication)

    # 4) Reattach to the Sales Master agent.
    print("[4] reattach toolset to agent")
    agents.update_agent(
        agent_name=SALES_AGENT,
        toolsets=[T.Agent.AgentToolset(toolset=TOOLSET, tool_ids=[OP_ID])],
        tools=[END_SESSION],
    )
    print("DONE. sales-adapter -> ", base, " (OIDC via CES service agent)")


if __name__ == "__main__":
    main()
