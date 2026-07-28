"""GATE TEST: can a CXAS Python tool reach the CES API to read a conversation?

Everything in the cross-channel hydration plan depends on this. The hydration
tool must, from inside the CXAS tool sandbox:
  1. import google.cloud / cxas libraries
  2. obtain credentials
  3. make an outbound call to ces.googleapis.com  (get_conversation)

If any of those is blocked, fetching history mid-session is impossible and the
fallback is passing context IN as a session variable instead.

This creates a throwaway tool that reports exactly which step fails, then invokes
it directly with Tools.execute_tool (no session/conversation needed, so it costs
almost nothing against the app's tight quota).

    python bootstrap/probe_tool_egress.py [CONVERSATION_ID]

Cleanup:  python bootstrap/probe_tool_egress.py --delete
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

from cxas_scrapi.core.tools import Tools

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

TOOL_ID = "probe-egress"
TOOL_NAME = "probe_egress"

# Each step reports independently so a failure tells us WHICH capability is
# missing (imports vs credentials vs network), not just "it didn't work".
PROBE_CODE = '''
def probe_egress(conversation_id: str) -> dict:
    """Diagnostic: report whether this tool sandbox can read a conversation."""
    result = {}

    # Step 1 — can we import the client libraries at all?
    try:
        from google.cloud import ces_v1beta
        result["import_ces"] = "ok"
    except Exception as e:
        result["import_ces"] = f"FAIL: {type(e).__name__}: {e}"
        return result

    # Step 2 — are ambient credentials available inside the sandbox?
    try:
        import google.auth
        creds, proj = google.auth.default()
        result["credentials"] = f"ok (project={proj})"
    except Exception as e:
        result["credentials"] = f"FAIL: {type(e).__name__}: {e}"
        return result

    # Step 3 — the real question: outbound call to the CES API.
    # get_conversation lives on AgentServiceClient (there is no separate
    # conversation-history client). The app is in the `us` multi-region, so the
    # client must target the regional endpoint or the call resolves nowhere.
    try:
        from google.api_core import client_options as co
        # SCRAPI targets the GLOBAL endpoint (ces.googleapis.com); the region
        # lives in the resource path, not a hostname prefix.
        client = ces_v1beta.AgentServiceClient(
            client_options=co.ClientOptions(api_endpoint="ces.googleapis.com")
        )
        name = (
            conversation_id
            if conversation_id.startswith("projects/")
            else f"{APP_PLACEHOLDER}/conversations/{conversation_id}"
        )
        conv = client.get_conversation(request={"name": name})
        result["get_conversation"] = f"ok turns={getattr(conv, 'turn_count', None)}"
    except Exception as e:
        result["get_conversation"] = f"FAIL: {type(e).__name__}: {str(e)[:200]}"

    # Step 4 — is SCRAPI itself available? (simpler code path if so)
    try:
        from cxas_scrapi.core.conversation_history import ConversationHistory
        ch = ConversationHistory(app_name=APP_PLACEHOLDER)
        c2 = ch.get_conversation(conversation_id)
        result["scrapi"] = f"ok turns={getattr(c2, 'turn_count', None)}"
    except Exception as e:
        result["scrapi"] = f"unavailable: {type(e).__name__}: {str(e)[:120]}"

    return result
'''.replace("APP_PLACEHOLDER", f'"{APP}"')


def main():
    tools = Tools(app_name=APP)

    if "--delete" in sys.argv:
        try:
            tools.delete_tool(f"{APP}/tools/{TOOL_ID}")
            print("deleted", TOOL_ID)
        except Exception as e:
            print("delete:", type(e).__name__, str(e)[:120])
        return

    conv_id = next((a for a in sys.argv[1:] if not a.startswith("-")), "")
    if not conv_id:
        sys.exit("usage: probe_tool_egress.py <CONVERSATION_ID>   "
                 "(any id from list_conversations)")

    # Recreate so re-runs pick up code edits.
    try:
        tools.delete_tool(f"{APP}/tools/{TOOL_ID}")
    except Exception:
        pass

    print(f"creating probe tool on {APP_ID}…")
    tools.create_tool(
        tool_id=TOOL_ID,
        display_name=TOOL_NAME,
        description="Diagnostic probe: can a tool read a conversation from inside the sandbox?",
        payload={"python_code": PROBE_CODE},
    )

    print(f"executing against conversation {conv_id}…\n")
    out = tools.execute_tool(tool_display_name=TOOL_NAME,
                             args={"conversation_id": conv_id})
    print(out)
    print("\nRead the three keys: import_ces / credentials / get_conversation.")
    print("All ok  -> hydration by fetching history is viable.")
    print("Any FAIL-> pass context IN via a session variable instead.")


if __name__ == "__main__":
    main()
