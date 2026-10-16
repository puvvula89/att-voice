import datetime as dt

import pytest

from support_mcp import progress_store
from support_mcp.tools_procedures import checkpoint, get_progress

RESET = "feature_network_reset-resetting-your-iphone-s-settings-and-network-settings"
CUST = "cust_2001"


@pytest.fixture(autouse=True)
def clean():
    progress_store.reset()


def test_checkpoint_releases_the_gated_step_and_says_what_to_say_first():
    r = checkpoint(CUST, "iphone-13", RESET, 4)
    assert r["text"] and r["call_ending"] and r["destructive"]
    assert "disconnect" in r["say_first"].lower() and "erase" in r["say_first"].lower()


def test_checkpoint_refuses_an_ungated_step():
    r = checkpoint(CUST, "iphone-13", RESET, 2)
    assert "error" in r and "text" not in r


def test_checkpoint_saves_progress_and_resume_starts_after_it():
    checkpoint(CUST, "iphone-13", RESET, 4)
    p = get_progress(CUST)["progress"]
    assert p["tutorial_id"] == RESET and p["step_n"] == 4 and p["resume_at"] == 5


def test_stale_progress_is_ignored(monkeypatch):
    checkpoint(CUST, "iphone-13", RESET, 4)
    rec = progress_store.load(CUST)
    rec["updated_at"] = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    progress_store.save(CUST, rec)
    monkeypatch.setenv("RESUME_WINDOW_MINUTES", "30")
    assert get_progress(CUST)["progress"] is None


def test_no_progress_is_none():
    assert get_progress("nobody")["progress"] is None
