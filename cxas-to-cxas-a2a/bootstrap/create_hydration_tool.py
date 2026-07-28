"""Wire the hydration service into CXAS: session variable + OpenAPI toolset.

Run by deploy_all.sh (step 3), or standalone:

    python bootstrap/create_hydration_tool.py https://cxas-hydration-xxxx.run.app

Creates/updates:
  * session variable `resume_conversation_id` (default EMPTY — the no-history
    case). For testing, set its value to the UUID used on the web app; the tool
    then loads that conversation on the next call. In production your lookup
    (ANI / customer id -> most recent conversation) supplies it instead.
  * OpenAPI toolset `hydration` -> POST {service}/hydrate, authenticated with the
    CES service agent's OIDC token (ServiceAgentIdTokenAuthConfig), matching the
    proven adapter pattern in cxas-to-adk.

WHY OPENAPI AND NOT A PYTHON TOOL
    CXAS python_function tools are fully network-isolated — no google libraries,
    no credentials, and DNS fails outright (verified by probe). Only OpenAPI /
    MCP / connector / remote-agent tools can reach an external service.
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.variables import Variables, VariableType

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

TOOLSET_ID = "hydration"
TOOLSET = f"{APP}/toolsets/{TOOLSET_ID}"

# Holds the prior conversation's id (== its session id). Empty by default, which
# the service treats as "no history" so the agent just greets normally.
RESUME_VAR = "resume_conversation_id"
RESUME_DEFAULT = os.environ.get("RESUME_CONVERSATION_ID", "")

# THE GATE. The before_model callback fires hydration only when this is non-empty
# — channel-agnostic, so whoever populates it (web client config frame, or the
# telephony variable mapping on GTP) decides whether hydration happens at all.
# Empty by default: an unidentified caller never triggers a lookup.
CUSTOMER_VAR = "customer_id"
CUSTOMER_DEFAULT = os.environ.get("HYDRATION_CUSTOMER_ID", "")

# Set by the callback, not by you. Latches the once-per-conversation decision
# ("done" / "skipped"). Declared so it shows up in the console alongside the rest.
LATCH_VAR = "hydrated"

# Qualified tool name the instruction must reference:
#   display_name `hydration` + operationId `load_prior_conversation`
TOOL_MACRO = "hydration_load_prior_conversation"

# NOTE: this description does NOT tell the model when to call the tool — it never
# does. A before_model callback (steering/hydration_callback.py) injects the call
# deterministically on the first model step, then hides the tool from the schema.
# What matters here is how to READ the result once it lands in context.
_DESCRIPTION = (
    "Loads the customer's previous conversation so this one can continue where it "
    "left off. found=false means there is no prior conversation — greet normally "
    "and never mention it. found=true means the customer is returning: welcome "
    "them back and ask whether they are calling about the topic in `topic`, using "
    "`summary` as background without reading it out."
)

SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "CXAS Hydration", "version": "1.0.0"},
    "servers": [{"url": "REPLACED_AT_RUNTIME"}],
    "paths": {
        "/hydrate": {
            "post": {
                "operationId": "load_prior_conversation",
                "summary": "Load a prior conversation's context for this customer.",
                "description": _DESCRIPTION,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "conversation_id": {
                                        "type": "string",
                                        "description": (
                                            "Id of the prior conversation, from the "
                                            "{resume_conversation_id} session variable. "
                                            "Send an empty string if it is not set."
                                        ),
                                    },
                                    "customer_id": {
                                        "type": "string",
                                        "description": "Optional customer id, for correlation only.",
                                    },
                                },
                                "required": ["conversation_id"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Prior context, or found=false when there is none.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "found": {"type": "boolean"},
                                        "summary": {"type": "string"},
                                        "turn_count": {"type": "integer"},
                                        "topic": {"type": "string"},
                                        "reason": {
                                            "type": "string",
                                            "description": (
                                                "Diagnostic only — why found is "
                                                "false. Never mention it to the "
                                                "customer."
                                            ),
                                        },
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: create_hydration_tool.py <HYDRATION_SERVICE_URL>")
    base = sys.argv[1].rstrip("/")
    print(f"app={APP}\nservice={base}")

    # 1) Session variables: the prior conversation id, the customer-id gate, and
    #    the callback's own latch.
    print("\n[1] Session variables")
    variables = Variables(app_name=APP)
    for name, default in (
        (RESUME_VAR, RESUME_DEFAULT),
        (CUSTOMER_VAR, CUSTOMER_DEFAULT),
        (LATCH_VAR, ""),
    ):
        try:
            variables.create_variable(
                variable_name=name,
                variable_type=VariableType.STRING,
                variable_value=default,
            )
            print(f"   {name} = {default!r}")
        except Exception as e:
            print(f"   {name}: (exists or not created: "
                  f"{type(e).__name__}: {str(e)[:100]})")

    # 2) OpenAPI toolset -> the hydration service, OIDC via the CES service agent.
    print(f"\n[2] Toolset {TOOLSET_ID} (OpenAPI + OIDC)")
    client = Agents(app_name=APP).client
    try:
        client.delete_toolset(request=T.DeleteToolsetRequest(name=TOOLSET, force=True))
        print("   (removed pre-existing toolset)")
    except Exception:
        pass

    schema = dict(SCHEMA)
    schema["servers"] = [{"url": base}]
    toolset = T.Toolset(
        display_name="hydration",
        open_api_toolset=T.OpenApiToolset(
            open_api_schema=json.dumps(schema),
            api_authentication=T.ApiAuthentication(
                service_agent_id_token_auth_config=T.ServiceAgentIdTokenAuthConfig()
            ),
        ),
    )
    created = client.create_toolset(
        request=T.CreateToolsetRequest(parent=APP, toolset_id=TOOLSET_ID, toolset=toolset)
    )
    print(f"   created: {created.name}")
    print(f"   tool macro for instructions: {{@TOOL: {TOOL_MACRO}}}")

    print("\nNEXT")
    print("  1. Attach the toolset + the firing callback to the root agent:")
    print("       python bootstrap/attach_hydration.py")
    print("  2. Arm a test — BOTH variables are needed. customer_id is the gate")
    print("     (empty = hydration never fires); resume_conversation_id is what")
    print("     gets loaded:")
    print("       python bootstrap/set_hydration_vars.py \\")
    print("           --customer-id cust-test --conversation-id <PRIOR_UUID>")
    print("  3. For a GTP test, also cut a NEW version and repoint the channel —")
    print("     channels are version-pinned, so editing the draft changes nothing.")


if __name__ == "__main__":
    main()
