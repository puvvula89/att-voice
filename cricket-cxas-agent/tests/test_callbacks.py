"""The Tech Support callbacks run inside the agent platform; here they run with stand-ins."""
import json
from pathlib import Path

from knowledge import load_datastore

SRC = Path(__file__).parent.parent / "app" / "agents" / "Tech_Support"
FILES = {"before_tool.py": "before_tool_callbacks", "after_tool.py": "after_tool_callbacks",
         "after_model.py": "after_model_callbacks", "before_agent.py": "before_agent_callbacks"}


class Ctx:
    def __init__(self, **v):
        self.variables, self.session_id = dict(v), "sess-1"


class Part:
    def __init__(self, text=None, function_call=None, data=None):
        self.text, self.function_call, self.data = text, function_call, data

    @classmethod
    def from_json(cls, data):
        return cls(data=data)


class Content:
    def __init__(self, parts=None):
        self.parts = parts or []


class LlmResponse:
    def __init__(self, content=None):
        self.content = content


def load(name):
    g = {"Tool": object, "CallbackContext": Ctx, "Content": Content, "LlmResponse": LlmResponse, "Part": Part}
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


def test_step_picture_goes_to_show_image_in_chat_and_is_dropped_on_voice():
    after = load("after_tool.py")["after_tool_callback"]
    chat = Ctx(channel="chat", image_links="{}", show_image="")
    out = after(None, {}, chat, {"step": 2, "of": 5, "text": "Tap Wi-Fi.", "image": "0123456789abcdef.png"})
    assert "image" not in out and out["picture"] and out["get_pictures"]
    assert chat.variables["show_image"] == "0123456789abcdef.png"
    voice = Ctx(channel="voice")
    out = after(None, {}, voice, {"step": 2, "of": 5, "text": "Tap Wi-Fi.", "image": "0123456789abcdef.png"})
    assert out == {"step": 2, "of": 5, "text": "Tap Wi-Fi."} and "show_image" not in voice.variables


def test_step_in_the_platforms_result_wrapper_is_handled_too():
    after = load("after_tool.py")["after_tool_callback"]
    ctx = Ctx(channel="chat", image_links="{}")
    resp = {"result": {"step": 1, "of": 7, "text": "x", "image": "0123456789abcdef.jpeg"}}
    out = after(None, {}, ctx, resp)
    assert out["result"]["picture"] and out["result"]["get_pictures"] and "image" not in out["result"]
    assert ctx.variables["show_image"] == "0123456789abcdef.jpeg"
    voice = after(None, {}, Ctx(channel="voice"), {"result": {"step": 1, "of": 7, "image": "a.png"}})
    assert voice == {"result": {"step": 1, "of": 7}}


def test_chat_step_with_signed_or_no_picture_does_not_ask_for_links():
    after = load("after_tool.py")["after_tool_callback"]
    ctx = Ctx(channel="chat", image_links=json.dumps({"a.png": "https://s/a"}))
    out = after(None, {}, ctx, {"step": 1, "of": 3, "text": "x", "image": "a.png"})
    assert out["picture"] and "get_pictures" not in out
    out = after(None, {}, ctx, {"step": 2, "of": 3, "text": "y"})
    assert out["picture"] is False and ctx.variables["show_image"] == "-"


def test_channel_follows_the_turns_modality():
    before = load("before_agent.py")["before_agent_callback"]
    for modality, channel in (("TEXT", "chat"), ("VOICE", "voice")):
        ctx = Ctx(_session={"modality": modality})
        assert before(ctx) is None and ctx.variables["channel"] == channel
    ctx = Ctx()
    before(ctx)
    assert ctx.variables["channel"] == "voice"


def _reply(ctx, *parts):
    return load("after_model.py")["after_model_callback"](ctx, LlmResponse(Content(list(parts))))


def test_chat_step_reply_gets_the_picture_and_quick_replies_once():
    ctx = Ctx(channel="chat", show_image="a.png", image_links=json.dumps({"a.png": "https://s/a"}))
    out = _reply(ctx, Part(text="Open Settings."))
    text, payload = out.content.parts
    cards = json.loads(payload.data)["richContent"]
    assert text.text == "Open Settings." and cards[0][0]["rawUrl"] == "https://s/a" and cards[1][0]["type"] == "chips"
    assert ctx.variables["show_image"] == "" and _reply(ctx, Part(text="ok")) is None


def test_chat_step_without_a_picture_gets_only_quick_replies():
    out = _reply(Ctx(channel="chat", show_image="-", image_links=""), Part(text="Restart it."))
    assert [c[0]["type"] for c in json.loads(out.content.parts[1].data)["richContent"]] == ["chips"]


def test_nothing_is_attached_on_voice_or_to_a_tool_call():
    assert _reply(Ctx(channel="voice", show_image="a.png"), Part(text="Open Settings.")) is None
    ctx = Ctx(channel="chat", show_image="a.png")
    assert _reply(ctx, Part(function_call={"name": "support_sign_images"})) is None
    assert ctx.variables["show_image"] == "a.png"


def test_signed_links_are_kept_by_picture_name():
    ctx = Ctx(image_links=json.dumps({"a.png": "old"}))
    out = load("after_tool.py")["after_tool_callback"](None, {"names": ""}, ctx, {"images": {"b.png": "https://s/b"}})
    assert out == {"images_ready": 1}
    assert json.loads(ctx.variables["image_links"]) == {"a.png": "old", "b.png": "https://s/b"}


def test_sign_images_is_filled_with_the_active_guides_pictures():
    steps = {"wifi": {"paths": [{"steps": [{"image": "a.png"}, {"image": ""}, {"image": "a.png"}]},
                                {"steps": [{"image": "b.jpeg"}]}]}}
    ctx = Ctx(walk=json.dumps({"active": "wifi"}), steps_by_id=json.dumps(steps))
    inp = {"names": ""}
    load("before_tool.py")["before_tool_callback"](None, inp, ctx)
    assert inp["names"] == "a.png,b.jpeg"
