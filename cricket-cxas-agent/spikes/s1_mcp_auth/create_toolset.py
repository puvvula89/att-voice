"""S1 spike — stand up a probe app and point an MCP toolset at the spike server.

Answers: does CXAS accept an MCP toolset aimed at a private Cloud Run service
authenticated with the CES service agent's ID token, and can a live agent turn
actually call a tool through it?

    ../../.venv/bin/python create_toolset.py https://cricket-s1-mcp-xxx.run.app/mcp/

The probe app is throwaway and separate from `cricket-care`, so a failed spike
leaves no wreckage in the real app. Tear it down with --delete once answered.

WHY MCP AND NOT A PYTHON TOOL
    The CXAS tool sandbox is network-isolated — no DNS, no credentials, no
    third-party libraries. Only OpenAPI / MCP / connector / remote-agent tools
    reach an external service.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, ".env"))

import google.cloud.ces_v1beta.types as T
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.agents import Agents

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
MODEL = os.environ.get("CARE_LIVE_MODEL", "gemini-3.1-flash-live")
APP_ID = os.environ.get("S1_APP_ID", "cricket-s1-probe")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

AGENT_ID = "s1-root"
AGENT = f"{APP}/agents/{AGENT_ID}"
TOOLSET_ID = "spike"
TOOLSET = f"{APP}/toolsets/{TOOLSET_ID}"
END_SESSION = f"{APP}/tools/end_session"

# Qualified tool name: <toolset display name>_<tool name on the MCP server>.
TOOL_MACRO = "spike_get_spike_secret"

INSTRUCTION = """<role>
You are a probe agent. Your only job is to fetch the spike secret and say it.
</role>
<persona>Brief and plain. No lists, no markdown.</persona>
<context>The account for this call is cust_1001. Use that exact value.</context>
<taskflow>
  <subtask name="fetch_secret">
    <trigger>The caller asks for the secret, the passphrase, or the spike token —
    including their first words to you</trigger>
    <step>Call {@TOOL: spike_get_spike_secret} with customer_id cust_1001.</step>
    <step>Say the returned `secret` value back, exactly as it came, and nothing
    else.</step>
    <rule>Never guess the secret. If the tool fails, say "tool call failed" and
    nothing else — do not improvise a value.</rule>
  </subtask>
  <subtask name="close_call">
    <trigger>The caller is done</trigger>
    <step>In ONE turn, say "Goodbye." and call {@TOOL: end_session}.</step>
  </subtask>
</taskflow>
"""


def _existing(fn, *a, **k):
    """Create-if-missing guard — CES reports an existing resource inconsistently."""
    try:
        return fn(*a, **k)
    except Exception as e:
        msg = str(e).lower()
        if "exist" in msg or "already_exists" in msg or "internal error" in msg or "500" in msg:
            print(f"   (create skipped: {type(e).__name__}) — will update in place")
            return None
        raise


def teardown(client):
    for label, call in (
        ("toolset", lambda: client.delete_toolset(
            request=T.DeleteToolsetRequest(name=TOOLSET, force=True))),
        ("app", lambda: Apps(project_id=PROJECT, location=LOCATION).delete_app(
            app_name=APP, force=True)),
    ):
        try:
            call()
            print(f"   deleted {label}")
        except Exception as e:
            print(f"   {label}: {type(e).__name__}: {str(e)[:100]}")


def main():
    args = [a for a in sys.argv[1:]]
    client = Agents(app_name=APP).client

    if "--delete" in args:
        print(f"tearing down {APP}")
        teardown(client)
        return

    if not args:
        sys.exit("usage: create_toolset.py <MCP_URL>   (e.g. https://…run.app/mcp/)")
    url = args[0]
    if not url.endswith("/"):
        # The MCP SDK serves streamable HTTP at a trailing-slash path; without it
        # the platform's list-tools call 307s and the toolset comes up empty.
        url += "/"
    print(f"app={APP}\nmcp={url}\nmodel={MODEL}")

    print(f"\n[1] App {APP_ID}")
    apps = Apps(project_id=PROJECT, location=LOCATION)
    _existing(apps.create_app, app_id=APP_ID, display_name="Cricket S1 Probe",
              model_settings=T.ModelSettings(model=MODEL))

    print(f"\n[2] MCP toolset {TOOLSET_ID} -> {url}")
    try:
        client.delete_toolset(request=T.DeleteToolsetRequest(name=TOOLSET, force=True))
        print("   (removed pre-existing toolset)")
    except Exception:
        pass
    toolset = T.Toolset(
        display_name="spike",
        mcp_toolset=T.McpToolset(
            server_address=url,
            api_authentication=T.ApiAuthentication(
                service_agent_id_token_auth_config=T.ServiceAgentIdTokenAuthConfig()
            ),
        ),
    )
    created = client.create_toolset(
        request=T.CreateToolsetRequest(parent=APP, toolset_id=TOOLSET_ID, toolset=toolset)
    )
    print(f"   created: {created.name}")

    # Listing the toolset back is the first real answer: the platform can only
    # enumerate these tools by calling the server, so a populated list proves
    # both reachability and that the ID token was accepted.
    fetched = client.get_toolset(request=T.GetToolsetRequest(name=TOOLSET))
    tools = list(getattr(fetched.mcp_toolset, "tool_overrides", []) or [])
    print(f"   discovered tool overrides: {[t.name for t in tools] or '(none reported)'}")

    print(f"\n[3] Agent {AGENT_ID} with the toolset attached")
    agents = Agents(app_name=APP)
    _existing(agents.create_agent, agent_id=AGENT_ID, display_name="S1 Probe",
              instruction=INSTRUCTION, model=MODEL, tools=[END_SESSION])
    # Toolsets go in the agent's dedicated `toolsets` field. Dropping a toolset
    # resource name into `tools` fails silently — the agent comes up with no
    # tools at all and improvises.
    agents.update_agent(
        agent_name=AGENT,
        instruction=INSTRUCTION,
        tools=[END_SESSION],
        toolsets=[T.Agent.AgentToolset(toolset=TOOLSET)],
    )
    print(f"   -> {AGENT}")

    print("\n[4] Point the app root at it")
    apps.update_app(app_name=APP, root_agent=AGENT)
    print("   root set")

    print("\nS1 IS ANSWERED BY A LIVE TURN, NOT BY THIS SCRIPT.")
    print("  Open the app in the console simulator and say: \"what is the spike secret?\"")
    print("  PASS: the agent speaks back the server's secret value.")
    print("  FAIL: \"tool call failed\", or a made-up value, or no tool call in the trace.")
    print(f"\n  Tear down after:  python {os.path.basename(__file__)} --delete")


if __name__ == "__main__":
    main()
