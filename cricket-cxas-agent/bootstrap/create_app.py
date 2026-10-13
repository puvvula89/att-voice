"""Create (or update in place) the Care app, the concierge, and the Tech Support agent.

    .venv/bin/python bootstrap/create_app.py

Idempotent: creates go through a create-if-missing guard, properties are set
with update calls. The app model is voice-optimized and must be set at creation.
The billing bundle adds its own child agent later; this script wires it into the
concierge only if it already exists.
"""
import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.apps import Apps

from common import (APP, APP_ID, BILLING_ID, CONCIERGE_ID, END_SESSION, LOCATION, MODEL, PROJECT,
                    TECH_ID, agent_name, existing, instruction)


def main():
    print(f"app={APP}\nmodel={MODEL}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    agents = Agents(app_name=APP)

    print(f"\n[1] App {APP_ID}")
    existing(apps.create_app, app_id=APP_ID, display_name="Cricket Care",
             model_settings=T.ModelSettings(model=MODEL))

    print(f"\n[2] Agent {TECH_ID}")
    tech_instruction = instruction("tech_support")
    existing(agents.create_agent, agent_id=TECH_ID, display_name="Tech Support",
             instruction=tech_instruction, model=MODEL, tools=[END_SESSION])
    agents.update_agent(agent_name=agent_name(TECH_ID), instruction=tech_instruction,
                        tools=[END_SESSION])

    print(f"\n[3] Agent {CONCIERGE_ID}")
    children = [agent_name(TECH_ID)]
    try:
        agents.get_agent(agent_name(BILLING_ID))
        children.append(agent_name(BILLING_ID))
        print("   billing-support found; wiring it as a child too")
    except Exception:  # noqa: BLE001
        pass
    concierge_instruction = instruction("care_concierge")
    existing(agents.create_agent, agent_id=CONCIERGE_ID, display_name="Care Concierge",
             instruction=concierge_instruction, model=MODEL, tools=[END_SESSION])
    agents.update_agent(agent_name=agent_name(CONCIERGE_ID), instruction=concierge_instruction,
                        tools=[END_SESSION], child_agents=children)

    print("\n[4] Root agent")
    apps.update_app(app_name=APP, root_agent=agent_name(CONCIERGE_ID))
    app = apps.get_app(APP)
    print(f"   root = {app.root_agent}")
    print(f"   agents = {[a.display_name for a in agents.list_agents()]}")
    print("\nNext: deploy_mcp.sh, then bootstrap/attach_support_toolset.py <MCP_URL>")


if __name__ == "__main__":
    main()
