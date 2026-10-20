"""Spike: can a callback see the current session id (so get_progress can index customer -> session)?

  probe.py <env>   install a before_model callback on spike-dstool that records what callback_context
                   exposes, run one turn, print it next to the session id the client used
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(sys.argv[1])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
APP = f"projects/{PROJECT}/locations/us/apps/spike-dstool"

PROBE = '''
from typing import Any, Optional


def before_model_callback(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    out = {"attrs": [a for a in dir(callback_context) if not a.startswith("__")]}
    for a in ("session_id", "conversation_id", "invocation_id", "session", "state", "agent_name", "user_id"):
        try:
            out[a] = str(getattr(callback_context, a))[:300]
        except Exception as e:
            out[a] = "ERR " + type(e).__name__
    try:
        out["vars"] = sorted(callback_context.variables.keys())[:40]
    except Exception as e:
        out["vars"] = "ERR " + type(e).__name__
    callback_context.variables["probe"] = str(out)
    return None
'''


def main():
    import google.cloud.ces_v1beta.types as T
    from cxas_scrapi.core.sessions import Sessions
    from google.cloud import ces_v1beta
    from google.protobuf import field_mask_pb2
    from google.protobuf.json_format import MessageToDict
    c = ces_v1beta.AgentServiceClient()
    a = c.get_agent(name=f"{APP}/agents/spike")
    saved = list(a.before_model_callbacks)
    a.before_model_callbacks = [T.Callback(python_code=PROBE)]
    c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["before_model_callbacks"]))
    try:
        s = Sessions(app_name=APP)
        sid = s.create_session_id()
        res = MessageToDict(s.run(sid, text="hello", variables={"device": "iphone-13"})._pb)
        probe = None
        for o in res.get("outputs", []):
            for m in o.get("diagnosticInfo", {}).get("messages", []):
                for ch in m.get("chunks", []):
                    probe = (ch.get("updatedVariables") or {}).get("probe", probe)
        print("client session id:", sid)
        print(probe)
    finally:
        a = c.get_agent(name=f"{APP}/agents/spike")
        a.before_model_callbacks = saved
        c.update_agent(agent=a, update_mask=field_mask_pb2.FieldMask(paths=["before_model_callbacks"]))


if __name__ == "__main__":
    main()
