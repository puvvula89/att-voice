"""Staleness gate: a prior conversation is only worth resuming for a while.

Offering to continue "your internet issue from earlier" is helpful minutes later
and baffling days later, so the digest is withheld once the conversation is older
than HYDRATION_MAX_AGE_MINUTES.

The age is measured from `end_time`, which CES stamps when the session's stream
closes — verified against a conversation abandoned by dropping the socket, which
is what a browser refresh does. A conversation still in progress has no end_time,
so start_time is the fallback.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "hydration"))
os.environ.setdefault("CXAS_PROJECT", "test-project")

import server
from server import _age_minutes, _condense


def _ago(minutes):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _conversation(**times):
    """A minimal conversation with one substantive customer turn."""
    return {
        "turn_count": 1,
        "turns": [{"messages": [
            {"role": "user", "chunks": [{"transcript": "my internet keeps dropping"}]},
        ]}],
        **times,
    }


@pytest.fixture
def window(monkeypatch):
    """Pin the window so the tests do not depend on the deployed default."""
    def _set(minutes):
        monkeypatch.setattr(server, "MAX_AGE_MINUTES", minutes)
    return _set


def test_recent_conversation_hydrates(window):
    window(10)
    out = _condense(_conversation(end_time=_ago(3)))
    assert out.found is True
    assert out.reason == "ok"
    assert "internet" in out.topic


def test_stale_conversation_is_withheld(window):
    window(10)
    out = _condense(_conversation(end_time=_ago(45)))
    assert out.found is False
    assert out.reason == "too_old"
    # Nothing about the prior conversation may leak once it is refused, or the
    # agent could still speak a topic it was told not to use.
    assert out.summary == ""
    assert out.topic == ""


def test_too_old_is_distinguishable_from_no_history(window):
    """The whole point of `reason`: a stale pointer is not a missing one."""
    window(10)
    assert _condense(_conversation(end_time=_ago(45))).reason == "too_old"
    assert _condense({"turn_count": 0, "turns": []}).reason == "empty"


def test_boundary_is_inclusive(window):
    """Exactly at the window still hydrates; the gate rejects strictly older."""
    window(10)
    assert _condense(_conversation(end_time=_ago(9.9))).found is True
    assert _condense(_conversation(end_time=_ago(10.1))).found is False


def test_falls_back_to_start_time_when_still_open(window):
    """An in-progress conversation has no end_time — age from start_time instead."""
    window(10)
    assert _condense(_conversation(start_time=_ago(2))).found is True
    assert _condense(_conversation(start_time=_ago(30))).reason == "too_old"


def test_end_time_wins_over_start_time(window):
    """A long conversation that ended recently is recent, not old."""
    window(10)
    out = _condense(_conversation(start_time=_ago(120), end_time=_ago(2)))
    assert out.found is True


def test_zero_disables_the_gate(window):
    window(0)
    assert _condense(_conversation(end_time=_ago(60 * 24 * 7))).found is True


def test_missing_timestamps_do_not_block(window):
    """No timestamps means the age is unknown; refusing on a guess would be worse."""
    window(10)
    assert _age_minutes({}) is None
    assert _condense(_conversation()).found is True


def test_accepts_iso_string_timestamps(window):
    """Conversation.to_dict renders timestamps as ISO strings, not datetimes."""
    window(10)
    stale = _ago(45).isoformat().replace("+00:00", "Z")
    assert _condense(_conversation(end_time=stale)).reason == "too_old"


def test_naive_timestamp_is_treated_as_utc(window):
    """A timestamp without a zone must not raise when subtracted from an aware now."""
    window(10)
    naive = _ago(45).replace(tzinfo=None).isoformat()
    assert _condense(_conversation(end_time=naive)).reason == "too_old"
