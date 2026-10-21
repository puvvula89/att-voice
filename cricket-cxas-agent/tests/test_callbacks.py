"""The Tech Support callbacks run inside the agent platform; here they run with stand-ins."""
import json
from pathlib import Path

from knowledge import load_datastore

SRC = Path(__file__).parent.parent / "app" / "agents" / "Tech_Support"
FILES = {"before_tool.py": "before_tool_callbacks", "after_tool.py": "after_tool_callbacks"}


class Ctx:
    def __init__(self, **v):
        self.variables, self.session_id = dict(v), "sess-1"


def load(name):
    g = {"Tool": object, "CallbackContext": Ctx, "Content": object}
    exec((SRC / FILES[name] / f"{FILES[name]}_01" / "python_code.py").read_text(), g)
    return g


def block(n, rec):
    return "\n".join([f"[{n}] {rec['title']}"] + [f"{k}: {rec[k]}" for k in ("device", "tutorial_id", "summary", "steps_b64")])


REC = load_datastore.records({"device": "iphone-13", "tutorials": [
    {"id": "wifi", "kind": "article", "title": "Wi-Fi slow", "summary": "Fix it.",
     "paths": [{"choices": [], "steps": [{"n": 1, "heading": "", "text": "Restart.", "notes": [], "links": []}]}]}]})[0]
OTHER = {**REC, "device": "moto-g-2025", "tutorial_id": "moto-wifi", "title": "Moto Wi-Fi"}
ANSWER = block(1, OTHER) + "\n\n" + block(2, REC)


def test_search_keeps_only_the_callers_phone_and_hides_the_steps():
    ctx = Ctx(steps_by_id="")
    out = load("after_tool.py")["after_tool_callback"](None, {"filter": 'device: ANY("iphone-13")'}, ctx, {"answer": ANSWER})
    assert out["answer"].startswith("[1] Wi-Fi slow") and "moto" not in out["answer"] and "steps_b64" not in out["answer"]
    saved = json.loads(ctx.variables["steps_by_id"])
    assert saved["wifi"]["title"] == "Wi-Fi slow" and saved["wifi"]["paths"][0]["steps"][0]["text"] == "Restart."


def test_search_without_the_device_filter_is_sent_back():
    out = load("after_tool.py")["after_tool_callback"](None, {}, Ctx(), {"answer": ANSWER})
    assert "filter" in out["answer"]


def test_progress_moves_the_saved_place_into_this_call():
    ctx = Ctx()
    resp = {"result": {"progress": {"step": 4}, "walk": "W", "steps_by_id": "S"}}
    out = load("after_tool.py")["after_tool_callback"](None, {}, ctx, resp)
    assert out == {"progress": {"step": 4}} and ctx.variables == {"walk": "W", "steps_by_id": "S"}


def test_progress_in_the_platforms_mcp_wrapper():
    ctx = Ctx()
    resp = {"text_output": [{"progress": {"step": 4}, "walk": "W", "steps_by_id": "S"}]}
    assert load("after_tool.py")["after_tool_callback"](None, {}, ctx, resp) == {"progress": {"step": 4}}
    assert ctx.variables["walk"] == "W"


def test_progress_as_mcp_text_content_is_read_too():
    ctx = Ctx()
    resp = {"content": [{"type": "text", "text": json.dumps({"progress": {"step": 2}, "walk": "W"})}]}
    assert load("after_tool.py")["after_tool_callback"](None, {}, ctx, resp) == {"progress": {"step": 2}}


def test_other_tools_pass_through():
    assert load("after_tool.py")["after_tool_callback"](None, {}, Ctx(), {"result": {"step": 1}}) is None
    assert load("after_tool.py")["after_tool_callback"](None, {}, Ctx(), {"progress": None}) is None


def test_save_progress_sends_the_pending_place_and_marks_it_saved():
    resume = {"tutorial_id": "wifi", "step": 4}
    walk = {"resume": {"tutorial_id": "wifi", "step": 3}, "pending": json.dumps({"resume": resume})}
    ctx = Ctx(walk=json.dumps(walk), steps_by_id="S")
    args = {"customer_id": "c", "walk": "", "steps_by_id": ""}
    assert load("before_tool.py")["before_tool_callback"](None, args, ctx) is None
    assert json.loads(args["walk"]) == {"resume": resume} and args["steps_by_id"] == "S"
    assert json.loads(ctx.variables["walk"])["saved"] == json.dumps(resume, sort_keys=True)


def test_other_tool_inputs_are_left_alone():
    args = {"customer_id": "c"}
    load("before_tool.py")["before_tool_callback"](None, args, Ctx(walk="W"))
    assert args == {"customer_id": "c"}
