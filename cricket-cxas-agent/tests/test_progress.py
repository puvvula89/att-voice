import datetime as dt
import json

import pytest

from support_mcp import progress_store
from support_mcp.tools_progress import get_progress, save_progress

CUST = "cust_2001"
WALK = json.dumps({"resume": {"tutorial_id": "wifi", "step": 4, "heading": "Restart", "risk": "drops", "choice": ""}})
STEPS = json.dumps({"wifi": {"title": "Wi-Fi slow", "paths": []}})


@pytest.fixture(autouse=True)
def clean():
    progress_store.reset()


def test_no_saved_place_is_none():
    assert get_progress(CUST) == {"progress": None}


def test_saved_place_comes_back_once_with_its_steps():
    assert save_progress(CUST, WALK, STEPS) == {"saved": True, "step": 4}
    r = get_progress(CUST)
    assert r["progress"]["step"] == 4 and r["progress"]["title"] == "Wi-Fi slow"
    assert r["walk"] == WALK and r["steps_by_id"] == STEPS
    assert get_progress(CUST) == {"progress": None}


def test_old_saved_place_is_not_resumed(monkeypatch):
    monkeypatch.setenv("RESUME_WINDOW_MINUTES", "30")
    save_progress(CUST, WALK, STEPS)
    rec = progress_store.load(CUST)
    progress_store.save(CUST, {**rec, "saved_at": rec["saved_at"] - dt.timedelta(minutes=45)})
    assert get_progress(CUST) == {"progress": None}


def test_nothing_to_save_before_the_walk_starts():
    assert save_progress(CUST, "", "")["saved"] is False
    assert progress_store.load(CUST) is None


def test_forget_drops_the_saved_place():
    save_progress(CUST, WALK, STEPS)
    progress_store.forget(CUST)
    assert get_progress(CUST) == {"progress": None}
