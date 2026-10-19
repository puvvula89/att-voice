"""one.py <env> <device> <query>: one turn on spike-dstool, print the result devices and tool args."""
import json, os, sys, time
from dotenv import load_dotenv
load_dotenv(sys.argv[1])
from cxas_scrapi.core.sessions import Sessions
from google.protobuf.json_format import MessageToDict
P = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
s = Sessions(app_name=f"projects/{P}/locations/us/apps/spike-dstool")
sid = s.create_session_id()
for i in range(6):
    try:
        r = s.run(sid, text=sys.argv[3], variables={"device": sys.argv[2]}); break
    except Exception as e:  # noqa: BLE001
        print("retry", str(e)[:60]); time.sleep(30)
v = {}
for o in MessageToDict(r._pb).get("outputs", []):
    for m in o.get("diagnosticInfo", {}).get("messages", []):
        for c in m.get("chunks", []):
            v.update(c.get("updatedVariables", {}) or {})
            if "toolCall" in c: print("args", json.dumps(c["toolCall"].get("args")))
            if "toolResponse" in c: print("resp", json.dumps(c["toolResponse"].get("response"))[:300])
            if "text" in c: print("text", c["text"][:200])
print("devices", v.get("ds_devices"), "ids", [i[:30] for i in json.loads(v.get("ds_ids", "[]"))])
