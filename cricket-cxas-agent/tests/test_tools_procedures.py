from support_mcp.tools_procedures import find_tutorials, get_step, get_tutorial

CALLS_IPHONE = "154674-can-t-make-or-receive-calls"
CALLS_GALAXY = "155859-can-t-make-or-receive-calls"
RESET = "feature_network_reset-resetting-your-iphone-s-settings-and-network-settings"
ONE_SIM = "I only have one SIM active (physical or eSIM)"
TWO_SIM = "I have two SIMs active (any combination of physical SIM and eSIM)"


def test_find_returns_article_first():
    r = find_tutorials("iphone-13", "can't make calls")
    assert r["results"][0]["kind"] == "article"


def test_find_unknown_device_is_an_error_not_an_exception():
    r = find_tutorials("pixel-9", "anything")
    assert r["results"] == [] and "device" in r["note"].lower()


def test_get_tutorial_summary_and_flags():
    t = get_tutorial("iphone-13", RESET)
    assert t["step_count"] == 5 and "steps" in t["summary"] and 4 in t["call_ending_steps"]


def test_branch_article_exposes_choices():
    t = get_tutorial("galaxy-a15-5g", CALLS_GALAXY)
    assert t["branch_question"] and len(t["choices"]) == 2


def test_get_step_follows_choice():
    one = get_step("galaxy-a15-5g", CALLS_GALAXY, 3, choice=ONE_SIM)
    two = get_step("galaxy-a15-5g", CALLS_GALAXY, 3, choice=TWO_SIM)
    assert one["text"] != two["text"]


def test_get_step_invalid_choice_lists_valid_ones():
    r = get_step("galaxy-a15-5g", CALLS_GALAXY, 3, choice="three SIMs")
    assert "error" in r and len(r["valid_choices"]) == 2


def test_get_step_links_resolve_to_ids():
    s = get_step("iphone-13", CALLS_IPHONE, 3)
    assert s["linked_procedures"] and all(p["id"] for p in s["linked_procedures"])


def test_last_step_flag():
    assert get_step("iphone-13", RESET, 5)["is_last"]
