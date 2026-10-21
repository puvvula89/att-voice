"""Create (or update in place) the Care app, the concierge, and the Tech Support agent.

    .venv/bin/python bootstrap/create_app.py

Idempotent: creates go through a create-if-missing guard, properties are set
with update calls. The app model is voice-optimized and must be set at creation.
The billing bundle adds its own child agent later; this script wires it into the
concierge only if it already exists.

Tech Support finds tutorials with the data store tool and walks them with the
next_step Python tool. Its callbacks keep the steps out of the model's view and
carry a dropped call's place into the callback (see agents/tech_support/).
"""
import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.variables import Variables, VariableType
from google.api_core import exceptions as gax
from google.cloud import ces_v1beta
from google.protobuf import field_mask_pb2

from common import (APP, APP_ID, BILLING_ID, CONCIERGE_ID, DATASTORE, END_SESSION, LOCATION, MODEL,
                    NEXT_STEP_TOOL, PROJECT, SEARCH_TOOL, TECH_ID, agent_name, existing, instruction,
                    source)

# Session variables the walk keeps; a Python tool sees only declared ones.
VARIABLES = {"walk": "The caller's place in the tutorial, kept at every step",
             "steps_by_id": "Steps of the tutorials found this call"}


def put_tool(client, tool_id: str, tool: T.Tool, field: str) -> None:
    name = f"{APP}/tools/{tool_id}"
    try:
        client.create_tool(parent=APP, tool_id=tool_id, tool=tool)
        print(f"   created {tool_id}")
    except gax.AlreadyExists:
        tool.name = name
        client.update_tool(tool=tool, update_mask=field_mask_pb2.FieldMask(paths=["display_name", field]))
        print(f"   updated {tool_id}")


def main():
    print(f"app={APP}\nmodel={MODEL}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    agents = Agents(app_name=APP)
    client = ces_v1beta.AgentServiceClient()

    print(f"\n[1] App {APP_ID}")
    existing(apps.create_app, app_id=APP_ID, display_name="Cricket Care",
             model_settings=T.ModelSettings(model=MODEL))
    v = Variables(app_name=APP)
    keep = [d for d in v.get_app(APP).variable_declarations if d.name not in VARIABLES]
    v.update_app(APP, variable_declarations=keep + [
        T.App.VariableDeclaration(name=n, description=d,
                                  schema={"type_": VariableType.STRING.value, "default": {"string_value": ""}})
        for n, d in VARIABLES.items()])
    print(f"   variables: {sorted(VARIABLES)}")

    print("\n[2] Tools: search_tutorials (data store), next_step (Python)")
    MT = T.DataStoreTool.ModalityConfig.ModalityType
    put_tool(client, "search-tutorials", T.Tool(display_name="search_tutorials", data_store_tool=T.DataStoreTool(
        name="search_tutorials",
        description="Find the troubleshooting guide for the caller's problem on their phone.",
        filter_parameter_behavior=T.DataStoreTool.FilterParameterBehavior.ALWAYS_INCLUDE,
        # Summaries off: the search callback needs each raw record to pick the steps out.
        modality_configs=[T.DataStoreTool.ModalityConfig(
            modality_type=mt, summarization_config=T.DataStoreTool.SummarizationConfig(disabled=True))
            for mt in (MT.TEXT, MT.AUDIO)],
        data_store_source=T.DataStoreTool.DataStoreSource(data_store=T.DataStore(name=DATASTORE)))),
        "data_store_tool")
    put_tool(client, "next-step", T.Tool(
        display_name="next_step", python_function=T.PythonFunction(python_code=source("tech_support", "next_step.py"))),
        "python_function")

    print(f"\n[3] Agent {TECH_ID}")
    tech_instruction = instruction("tech_support")
    tools = [END_SESSION, SEARCH_TOOL, NEXT_STEP_TOOL]
    existing(agents.create_agent, agent_id=TECH_ID, display_name="Tech Support",
             instruction=tech_instruction, model=MODEL, tools=tools)
    tech = client.get_agent(name=agent_name(TECH_ID))
    tech.instruction = tech_instruction
    tech.tools[:] = tools
    tech.before_tool_callbacks = [T.Callback(python_code=source("tech_support", "before_tool.py"))]
    tech.after_tool_callbacks = [T.Callback(python_code=source("tech_support", "after_tool.py"))]
    client.update_agent(agent=tech, update_mask=field_mask_pb2.FieldMask(
        paths=["instruction", "tools", "before_tool_callbacks", "after_tool_callbacks"]))

    print(f"\n[4] Agent {CONCIERGE_ID}")
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

    print("\n[5] Root agent")
    apps.update_app(app_name=APP, root_agent=agent_name(CONCIERGE_ID))
    print(f"   root = {apps.get_app(APP).root_agent}")
    print(f"   agents = {[a.display_name for a in agents.list_agents()]}")


if __name__ == "__main__":
    main()
