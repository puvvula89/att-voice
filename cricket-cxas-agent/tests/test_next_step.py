"""next_step runs inside the agent platform; here it runs with stand-ins for its variable store."""
import json
from pathlib import Path

import pytest

from knowledge import load_datastore

ROOT = Path(__file__).parent.parent
SRC = (ROOT / "agents" / "tech_support" / "next_step.py").read_text()
# What the search callback decodes: the data store records, with linked how-tos attached.
CAT = {d: {r["tutorial_id"]: {"title": r["title"], **load_datastore.decode_steps(r["steps_b64"])}
           for r in load_datastore.records(json.loads((ROOT / "knowledge" / "catalog" / f"{d}.json").read_text()))}
       for d in ("iphone-13", "moto-g-2025")}
WIFI = "156126-wi-fi-connection-issues-or-slowdowns"
POWER = "feature_power_on-powering-your-iphone-on-and-off"
WIFI_CALLING = "feature_tbs_wifi_calling_issues-troubleshooting-why-wi-fi-calling-isn-t-working"
MOTO_CALLS = "156118-can-t-make-or-receive-calls"


class Ctx:
    def __init__(self, store):
        self.variables = store


@pytest.fixture
def walk():
    store = {}
    g = {"get_variable": store.get, "set_variable": store.__setitem__}
    exec(SRC, g)
    cb = {"Tool": object, "CallbackContext": Ctx}
    exec((ROOT / "agents" / "tech_support" / "before_tool.py").read_text(), cb)

    def save():
        """What the agent's save_progress call does: the callback picks what to send and marks it saved."""
        args = {"customer_id": "c", "walk": "", "steps_by_id": ""}
        cb["before_tool_callback"](None, args, Ctx(store))
        return json.loads(args["walk"])
    g["save"] = save

    def load(device, *ids):
        store["steps_by_id"] = json.dumps({i: CAT[device][i] for i in ids})
    g["load"], g["state"] = load, lambda: json.loads(store["walk"])
    return g


def test_safe_steps_come_one_at_a_time_and_keep_the_place(walk):
    walk["load"]("iphone-13", WIFI)
    for n in (1, 2, 3):
        r = walk["next_step"](WIFI)
        assert r["step"] == n and "save_first" not in r
        assert walk["state"]()["resume"]["step"] == n


def test_call_ending_step_needs_a_warning_a_save_and_a_yes(walk):
    walk["load"]("iphone-13", WIFI)
    for _ in range(3):
        walk["next_step"](WIFI)
    first = walk["next_step"](WIFI, caller_confirmed=True)
    assert first["needs_confirmation"] and first["save_first"] and "text" not in first and first["if_unclear"]
    saved = walk["save"]()
    assert saved["resume"]["step"] == 4 and saved["resume"]["risk"] == "drops"
    assert saved["progress"][WIFI]["done"] == 4  # a callback continues after the restart
    assert "needs_confirmation" in walk["next_step"](WIFI)  # no yes: still withheld
    step = walk["next_step"](WIFI, caller_confirmed=True)
    assert step["step"] == 4 and step["call_ending"] and step["how_to"]


def test_saving_too_early_does_not_release_the_step(walk):
    walk["load"]("iphone-13", WIFI)
    for _ in range(3):
        walk["next_step"](WIFI)
    walk["save"]()  # the model saved before asking for the step: that saves step 3
    first = walk["next_step"](WIFI)
    assert first["save_first"]
    assert walk["save"]()["resume"]["step"] == 4


def test_might_drop_step_is_given_once_saved_without_asking(walk):
    walk["load"]("iphone-13", WIFI_CALLING)
    for _ in range(3):
        walk["next_step"](WIFI_CALLING)
    gate = walk["next_step"](WIFI_CALLING)
    assert gate == {"step": 4, "of": gate["of"], "save_first": True}
    assert walk["save"]()["resume"]["risk"] == "may_drop"
    r = walk["next_step"](WIFI_CALLING)
    assert r["step"] == 4 and "needs_confirmation" not in r


def test_repeat_gives_the_same_step(walk):
    walk["load"]("iphone-13", WIFI)
    walk["next_step"](WIFI)
    walk["next_step"](WIFI)
    assert walk["next_step"](WIFI, action="repeat")["step"] == 2


def test_linked_guide_returns_to_the_main_one(walk):
    walk["load"]("iphone-13", WIFI, POWER)
    for _ in range(3):
        walk["next_step"](WIFI)
    r = {}
    while not r.get("finished"):
        if r.get("save_first"):
            walk["save"]()
        r = walk["next_step"](POWER, caller_confirmed=r.get("needs_confirmation", False))
    assert r["return_to"] == WIFI
    assert walk["next_step"](WIFI)["step"] == 4


def test_branch_asks_then_follows_the_choice(walk):
    walk["load"]("moto-g-2025", MOTO_CALLS)
    r = {}
    while not r.get("needs_choice"):
        if r.get("save_first"):
            walk["save"]()
        r = walk["next_step"](MOTO_CALLS, caller_confirmed=bool(r.get("needs_confirmation")))
    assert r["question"] and len(r["choices"]) >= 2
    assert walk["next_step"](MOTO_CALLS, choice="not a choice")["error"]
    nxt = walk["next_step"](MOTO_CALLS, choice=r["choices"][-1])
    assert nxt.get("step") or nxt.get("needs_confirmation")


def test_unknown_tutorial_says_to_search_first(walk):
    walk["load"]("iphone-13", WIFI)
    assert "Search" in walk["next_step"]("nope")["error"]
