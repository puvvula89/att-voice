from support_mcp.tools_procedures import get_step, get_tutorial

RESET = "feature_network_reset-resetting-your-iphone-s-settings-and-network-settings"
CALLS_GALAXY = "155859-can-t-make-or-receive-calls"
ONE_SIM = "I only have one SIM active (physical or eSIM)"


def test_single_path_tutorial_returns_every_step_with_gated_text_withheld():
    t = get_tutorial("iphone-13", RESET)
    assert t["path_complete"] and [s["n"] for s in t["steps"]] == [1, 2, 3, 4, 5]
    gated = [s for s in t["steps"] if s["gated"]]
    assert [s["n"] for s in gated] == [4]
    assert "text" not in gated[0] and gated[0]["call_ending"]


def test_branching_tutorial_without_choice_stops_at_the_fork():
    t = get_tutorial("galaxy-a15-5g", CALLS_GALAXY)
    assert not t["path_complete"] and t["branch_question"] and len(t["choices"]) == 2
    assert [s["n"] for s in t["steps"]] == [1, 2]          # shared steps only


def test_branching_tutorial_with_choice_returns_that_branch():
    t = get_tutorial("galaxy-a15-5g", CALLS_GALAXY, choice=ONE_SIM)
    assert t["path_complete"] and t["last_step"] == 7
    assert [s["n"] for s in t["steps"] if s["gated"]] == [3, 6]


def test_invalid_choice_lists_valid_ones():
    r = get_tutorial("galaxy-a15-5g", CALLS_GALAXY, choice="three SIMs")
    assert "error" in r and len(r["valid_choices"]) == 2


def test_long_path_is_windowed(monkeypatch):
    from support_mcp import tools_procedures as P
    monkeypatch.setattr(P, "WINDOW", 2)
    t = get_tutorial("iphone-13", RESET)
    assert [s["n"] for s in t["steps"]] == [1, 2] and t["next_from"] == 3
    t2 = get_tutorial("iphone-13", RESET, from_step=3)
    assert [s["n"] for s in t2["steps"]] == [3, 4]


def test_get_step_refuses_a_gated_step():
    r = get_step("iphone-13", RESET, 4)
    assert r["gated"] and "checkpoint" in r["error"] and "text" not in r
