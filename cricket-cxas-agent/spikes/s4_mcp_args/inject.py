"""Spike: does a before_tool_callback's change to an MCP tool's input reach the server?

  inject.py <env>   on the deployed cricket-care app, overwrite get_progress's session_id in a
                    before_tool_callback, run one turn, print the args the server got; then restore
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(sys.argv[1])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
APP = f"projects/{PROJECT}/locations/us/apps/{os.environ.get('CARE_APP_ID', 'cricket-care')}"

CB = '''
from typing import Any, Optional


def before_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext) -> Optional[dict[str, Any]]:
    if "session_id" in input:
        input["session_id"] = "INJECTED-" + str(input["session_id"])[:8]
    return None
'''


def main():
    import google.cloud.ces_v1beta.types as T
    from cxas_scrapi.core.sessions import Sessions
    from google.cloud import ces_v1beta
    from google.protobuf import field_mask_pb2
    from google.protobuf.json_format import MessageToDict
    c = ces_v1beta.AgentServiceClient()
    name = f"{APP}/agents/tech-support"
    a = c.get_agent(name=name)
    a.before_tool_callbacks = [T.Callback(python_code=CB)]
    c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["before_tool_callbacks"]))
    try:
        s = Sessions(app_name=APP)
        sid = s.create_session_id()
        res = MessageToDict(s.run(sid, text="my wifi is really slow")._pb)
        for o in res.get("outputs", []):
            for m in o.get("diagnosticInfo", {}).get("messages", []):
                for ch in m.get("chunks", []):
                    if "toolCall" in ch and "progress" in json.dumps(ch["toolCall"]):
                        print("call:", json.dumps(ch["toolCall"].get("args")))
                    if "toolResponse" in ch and "progress" in json.dumps(ch["toolResponse"]):
                        print("resp:", json.dumps(ch["toolResponse"])[:300])
    finally:
        a = c.get_agent(name=name)
        a.before_tool_callbacks = []
        c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["before_tool_callbacks"]))


if __name__ == "__main__":
    main()
