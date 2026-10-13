"""Point an MCP toolset at the deployed support server and attach it to Tech Support.

    .venv/bin/python bootstrap/attach_support_toolset.py https://cricket-support-mcp-xxx.run.app/mcp

The toolset is recreated on every run (delete-if-exists, then create) so a new
server URL always lands. Auth is the CES service agent's own ID token; the Cloud
Run service must grant it roles/run.invoker (deploy_mcp.sh does).

The server mounts streamable HTTP at /mcp with NO trailing slash in this SDK
version; the slash form 307-redirects and the platform's discovery then returns
an empty tool list.
"""
import sys

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents

from common import APP, SUPPORT_TOOLSET_ID, TECH_ID, agent_name

TOOLSET = f"{APP}/toolsets/{SUPPORT_TOOLSET_ID}"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: attach_support_toolset.py <MCP_URL ending in /mcp>")
    url = sys.argv[1].rstrip("/")
    agents = Agents(app_name=APP)
    client = agents.client

    print(f"[1] Toolset {SUPPORT_TOOLSET_ID} -> {url}")
    try:
        client.delete_toolset(request=T.DeleteToolsetRequest(name=TOOLSET, force=True))
        print("   (removed pre-existing toolset)")
    except Exception:  # noqa: BLE001
        pass
    toolset = T.Toolset(
        display_name=SUPPORT_TOOLSET_ID,
        mcp_toolset=T.McpToolset(
            server_address=url,
            api_authentication=T.ApiAuthentication(
                service_agent_id_token_auth_config=T.ServiceAgentIdTokenAuthConfig()
            ),
        ),
    )
    created = client.create_toolset(
        request=T.CreateToolsetRequest(parent=APP, toolset_id=SUPPORT_TOOLSET_ID, toolset=toolset)
    )
    print(f"   created {created.name}")

    fetched = client.get_toolset(request=T.GetToolsetRequest(name=TOOLSET))
    overrides = list(getattr(fetched.mcp_toolset, "tool_overrides", []) or [])
    print(f"   discovered tools: {[t.name for t in overrides] or '(none reported by get; verify in console)'}")

    print(f"[2] Attach to {TECH_ID}")
    agents.update_agent(agent_name=agent_name(TECH_ID),
                        toolsets=[T.Agent.AgentToolset(toolset=TOOLSET)])
    tech = agents.get_agent(agent_name(TECH_ID))
    print(f"   toolsets on agent: {[ts.toolset.rsplit('/', 1)[-1] for ts in tech.toolsets]}")
    print("\nOpen the app in the console simulator and type: \"my wifi is really slow\"")
    print("PASS: the trace shows support_get_lines, then outage/usage checks, then find_tutorials.")


if __name__ == "__main__":
    main()
