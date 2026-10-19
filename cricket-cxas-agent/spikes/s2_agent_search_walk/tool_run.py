"""Spike: the same phrases through the CES data store tool (query rewriting included).

The device filter comes from the session variable `device`: a before_tool_callback writes it into the
tool's filter argument, so the model never authors it. An after_tool_callback records the ranked
tutorial ids, their devices and the tool input.

  app <env>            throwaway app spike-dstool on data store spike-meta
  run <env> [limit]    one session per phrase; writes tool_results.json and prints top-1 / top-3
  cleanup <env>        delete the app
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(sys.argv[2])
PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
DS = f"projects/{PROJECT}/locations/global/collections/default_collection/dataStores/spike-meta"
APP = f"projects/{PROJECT}/locations/us/apps/spike-dstool"
MODEL = "gemini-3.5-flash"
HERE = Path(__file__).parent

BEFORE = '''
import json
from typing import Any, Optional


def before_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext) -> Optional[dict[str, Any]]:
    dev = callback_context.variables.get("device")
    if dev:
        input["filter"] = 'device: ANY("' + str(dev) + '")'
    callback_context.variables["ds_input"] = json.dumps(input)
    return None
'''

AFTER = '''
import json
import re
from typing import Any, Optional


def after_tool_callback(tool: Tool, input: dict[str, Any], callback_context: CallbackContext,
                        tool_response: dict[str, Any]) -> Optional[dict[str, Any]]:
    answer = str(tool_response.get("answer", ""))
    callback_context.variables["ds_ids"] = json.dumps(re.findall(r"tutorial_id: ?([^,}\\s]+)", answer))
    callback_context.variables["ds_devices"] = json.dumps(re.findall(r"device: ?([a-z0-9-]+)", answer))
    callback_context.variables["ds_input_after"] = json.dumps(input)
    callback_context.variables["ds_answer_len"] = str(len(answer))
    return None
'''


def app():
    import google.cloud.ces_v1beta.types as T
    from cxas_scrapi.core.agents import Agents
    from cxas_scrapi.core.apps import Apps
    from google.cloud import ces_v1beta
    try:
        Apps(project_id=PROJECT, location="us").create_app(
            app_id="spike-dstool", display_name="Spike dstool", model_settings=T.ModelSettings(model=MODEL))
    except Exception as e:  # noqa: BLE001
        print("app:", type(e).__name__, str(e)[:200])
    MT = T.DataStoreTool.ModalityConfig.ModalityType
    tool = T.Tool(display_name="search_tutorials", data_store_tool=T.DataStoreTool(
        name="search_tutorials", description="Find phone troubleshooting tutorials for the caller's problem.",
        filter_parameter_behavior=T.DataStoreTool.FilterParameterBehavior.ALWAYS_INCLUDE,
        modality_configs=[T.DataStoreTool.ModalityConfig(
            modality_type=mt, summarization_config=T.DataStoreTool.SummarizationConfig(disabled=True))
            for mt in (MT.TEXT, MT.AUDIO)],
        data_store_source=T.DataStoreTool.DataStoreSource(data_store=T.DataStore(name=DS))))
    try:
        ces_v1beta.AgentServiceClient().create_tool(parent=APP, tool_id="search-tutorials", tool=tool)
        print("tool created")
    except Exception as e:  # noqa: BLE001
        print("tool:", type(e).__name__, str(e)[:400])
    try:
        Agents(app_name=APP).create_agent(
            agent_id="spike", display_name="Spike", model=MODEL,
            instruction="When the user describes a phone problem, call search_tutorials once with their problem, "
                        "then reply with the titles of the results only.",
            tools=[f"{APP}/tools/search-tutorials"],
            before_tool_callbacks=[T.Callback(python_code=BEFORE)],
            after_tool_callbacks=[T.Callback(python_code=AFTER)])
        print("agent created")
    except Exception as e:  # noqa: BLE001
        print("agent:", type(e).__name__, str(e)[:400])
    Apps(project_id=PROJECT, location="us").update_app(app_name=APP, root_agent=f"{APP}/agents/spike")
    print("app ready")


def variables(conv: dict) -> dict:
    out = {}
    for t in conv.get("turns", []):
        for m in t.get("messages", []):
            for c in m.get("chunks", []):
                out.update(c.get("updatedVariables", {}) or {})
    return out


def run(limit):
    from cxas_scrapi.core.sessions import Sessions
    from google.cloud import ces_v1beta
    from google.protobuf.json_format import MessageToDict
    phrases = json.load(open(HERE / "phrases.json"))[:limit]
    path = HERE / "tool_results.json"
    rows = json.load(open(path)) if path.exists() else []
    rows = [r for r in rows if r["input"]]  # empty input = the run never reached the tool; retry it
    done = {(r["device"], r["q"]) for r in rows}
    s, client = Sessions(app_name=APP), ces_v1beta.AgentServiceClient()
    for p in phrases:
        if (p["device"], p["q"]) in done:
            continue
        sid = s.create_session_id()
        res = None
        for i in range(10):
            try:
                res = MessageToDict(s.run(sid, text=p["q"], variables={"device": p["device"]})._pb)
                break
            except Exception as e:  # noqa: BLE001
                print("  run", type(e).__name__, str(e)[:120], flush=True); time.sleep(30 * (i + 1))
        if res is None:
            print("  gave up", p["q"], flush=True)
            continue
        v = {}
        for o in res.get("outputs", []):
            v.update(variables({"turns": [o.get("diagnosticInfo", {})]}))
        ids = json.loads(v.get("ds_ids", "[]"))
        ok = lambda t: any(t.startswith(o) for o in p["ok"])  # noqa: E731
        row = {"device": p["device"], "q": p["q"], "ids": ids,
               "devices": json.loads(v.get("ds_devices", "[]")), "input": v.get("ds_input_after", ""),
               "top1": bool(ids) and ok(ids[0]), "top3": any(ok(t) for t in ids[:3])}
        rows.append(row)
        json.dump(rows, open(path, "w"), indent=1)
        print(f"{'+' if row['top1'] else ('~' if row['top3'] else '-')} {p['q'][:45]:45s} {row['input'][:110]} "
              f"devs={sorted(set(row['devices']))}", flush=True)
        time.sleep(20)
    n = len(rows)
    print(f"tool  top1 {sum(r['top1'] for r in rows)}/{n}  top3 {sum(r['top3'] for r in rows)}/{n}")


def cleanup():
    from google.cloud import ces_v1beta
    ces_v1beta.AgentServiceClient().delete_app(name=APP).result(timeout=120)
    print("deleted", APP)


if __name__ == "__main__":
    {"app": app, "run": lambda: run(int(sys.argv[3]) if len(sys.argv) > 3 else 999),
     "cleanup": cleanup}[sys.argv[1]]()
