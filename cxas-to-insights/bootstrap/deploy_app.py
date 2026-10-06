"""Create and deploy the demo CES app, end to end.

Chain (each step is idempotent enough to re-run):
    app -> root agent -> point app at root agent -> app version -> deployment

Run:
    python bootstrap/deploy_app.py

Gotchas this script encodes, all hit while building the runbook:
  * Every user-specified resource ID must match `[a-zA-Z0-9][a-zA-Z0-9-_]{4,35}`
    — i.e. 5-36 chars. "root" is rejected; "concierge" is fine.
  * `App.modelSettings.model` is effectively required. Creating an app with only
    a displayName fails with a bare "an internal error has occurred".
  * The model must exist in CXAS_LOCATION. `gemini-2.5-flash` is NOT available
    in `us` and fails validation; `gemini-3.5-flash` is.
  * The documented draft alias `versions/-` is REJECTED by CreateDeployment
    (the `-` fails the resource-ID regex). You must cut a real app version and
    deploy that.
  * App/agent/version/deployment creates are long-running operations and can
    outlast a short poll. A timeout here means "unknown", not "failed" — the
    script re-reads the resource to decide.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ces_client import (  # noqa: E402
    AGENT_ID, APP, APP_ID, APP_MODEL, CES_ROOT, LOCATION, PROJECT, call, wait_lro,
)

VERSION_ID = "version-0001"
DEPLOYMENT_ID = "deploy-0001"

INSTRUCTION = """<role>
You are a support concierge for a mobile carrier. You answer the customer's
question briefly and politely.
</role>
<persona>Warm, concise, plain text. Two sentences or fewer per reply.</persona>
<taskflow>
  <subtask name="help">
    <trigger>Any customer question about their account, bill, or service</trigger>
    <step>Acknowledge the issue, give a brief helpful answer, and ask whether
    there is anything else.</step>
  </subtask>
  <subtask name="end_conversation">
    <trigger>The customer says goodbye or indicates they are done</trigger>
    <step>Thank them warmly and close the conversation.</step>
  </subtask>
</taskflow>
"""


def exists(url):
    return "__err" not in call("GET", url)


def main():
    print(f"project={PROJECT} location={LOCATION} app={APP_ID}")

    # 1. App.
    if exists(f"{CES_ROOT}/apps/{APP_ID}"):
        print("1. app: already exists")
    else:
        print("1. app: creating")
        wait_lro(
            call("POST", f"{CES_ROOT}/apps?appId={APP_ID}",
                 {"displayName": "Insights Demo", "modelSettings": {"model": APP_MODEL}}),
            "app",
        )

    # 2. Root agent.
    agent_url = f"{CES_ROOT}/apps/{APP_ID}/agents/{AGENT_ID}"
    if exists(agent_url):
        print("2. agent: already exists")
    else:
        print("2. agent: creating")
        wait_lro(
            call("POST", f"{CES_ROOT}/apps/{APP_ID}/agents?agentId={AGENT_ID}",
                 {"displayName": "Concierge", "instruction": INSTRUCTION}),
            "agent",
        )

    # 3. Make it the entry point. Without this the app has no root agent and
    #    every session fails.
    print("3. root agent: pointing app at it")
    r = call("PATCH", f"{CES_ROOT}/apps/{APP_ID}?updateMask=rootAgent",
             {"rootAgent": f"{APP}/agents/{AGENT_ID}"})
    print("  ", "ok" if "__err" not in r else r)

    # 4. App version. Required because `versions/-` is rejected downstream.
    version_url = f"{CES_ROOT}/apps/{APP_ID}/versions/{VERSION_ID}"
    if exists(version_url):
        print("4. version: already exists")
    else:
        print("4. version: creating")
        wait_lro(
            call("POST", f"{CES_ROOT}/apps/{APP_ID}/versions?appVersionId={VERSION_ID}",
                 {"displayName": "v1"}),
            "version",
        )

    # 5. Deployment with a channel profile. This is what production traffic
    #    uses, and what the Monitoring view reports on.
    dep_url = f"{CES_ROOT}/apps/{APP_ID}/deployments/{DEPLOYMENT_ID}"
    if exists(dep_url):
        print("5. deployment: already exists")
    else:
        print("5. deployment: creating")
        wait_lro(
            call("POST", f"{CES_ROOT}/apps/{APP_ID}/deployments?deploymentId={DEPLOYMENT_ID}",
                 {"displayName": "prod api channel",
                  "appVersion": f"{APP}/versions/{VERSION_ID}",
                  "channelProfile": {"channelType": "API", "profileId": "apiprofile"}}),
            "deployment",
        )

    print("\nLogging settings as deployed (confirm conversation logging is ON):")
    app = call("GET", f"{CES_ROOT}/apps/{APP_ID}")
    print("  ", app.get("loggingSettings"))
    cls = (app.get("loggingSettings") or {}).get("conversationLoggingSettings") or {}
    if cls.get("disableConversationLogging"):
        print("   WARNING: disableConversationLogging=true — nothing will reach Insights.")
    else:
        print("   disableConversationLogging is not set -> logging is ON (the default).")

    print(f"\nDeployment: {APP}/deployments/{DEPLOYMENT_ID}")
    print("Next: python verify/run_conversation.py")


if __name__ == "__main__":
    main()
