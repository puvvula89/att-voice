"""Console service: event files in, shaped call reports out."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from bridge.metrics import CallMetrics


def write_events(root, conv, lines):
    path = os.path.join(root, conv)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "events.jsonl"), "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))
    import importlib

    from console import app as module
    importlib.reload(module)
    return TestClient(module.app), str(tmp_path)


def test_lists_calls_newest_first(client):
    c, root = client
    write_events(root, "call-a", [{"event": "speech_onset", "ts": 1.0, "direction": "d", "utterance": 1}])
    write_events(root, "call-b", [{"event": "speech_onset", "ts": 2.0, "direction": "d", "utterance": 1}])
    body = c.get("/api/calls").json()
    assert {x["conv"] for x in body["calls"]} == {"call-a", "call-b"}
    assert body["current"] == body["calls"][0]["conv"]


def test_builds_utterance_with_hops_and_transcripts(client):
    c, root = client
    write_events(root, "conv1", [
        {"event": "speech_onset", "ts": 100.0, "direction": "caller-to-agent", "utterance": 1},
        {"event": "model_send", "ts": 100.06, "direction": "caller-to-agent", "utterance": 1, "send_ms": 60},
        {"event": "transcript", "ts": 100.5, "direction": "caller-to-agent", "utterance": 1,
         "kind": "input", "text": "नमस्ते", "language": "hi"},
        {"event": "first_audio", "ts": 102.0, "direction": "caller-to-agent", "utterance": 1, "ttfa_ms": 2000},
        {"event": "transcript", "ts": 102.1, "direction": "caller-to-agent", "utterance": 1,
         "kind": "output", "text": "Hello", "language": "en"},
        {"event": "utterance", "ts": 105.0, "direction": "caller-to-agent", "utterance": 1,
         "send_ms": 60, "ttfa_ms": 2000, "ttft_ms": 2100, "first_send_ms": 2010},
    ])
    body = c.get("/api/calls/conv1").json()
    u = body["directions"]["caller-to-agent"]["utterances"][0]

    assert u["source"] == "नमस्ते" and u["translation"] == "Hello"
    assert (u["send_ms"], u["ttfa_ms"], u["first_send_ms"]) == (60, 2000, 2010)
    assert u["total_ms"] == 2010
    # Arrival is onset plus the measured delay, so the console can show both clocks.
    assert u["arrival_ts"] == pytest.approx(102.01)


def test_transcript_fragments_concatenate(client):
    c, root = client
    write_events(root, "conv2", [
        {"event": "speech_onset", "ts": 1.0, "direction": "d", "utterance": 1},
        {"event": "transcript", "ts": 1.1, "direction": "d", "utterance": 1, "kind": "output", "text": "Hel"},
        {"event": "transcript", "ts": 1.2, "direction": "d", "utterance": 1, "kind": "output", "text": "lo"},
    ])
    body = c.get("/api/calls/conv2").json()
    assert body["directions"]["d"]["utterances"][0]["translation"] == "Hello"


def test_stats_report_median_per_hop(client):
    c, root = client
    # Spaced well beyond the turn gap so each stays its own turn.
    write_events(root, "conv3", [
        e for n, first in ((1, 1000), (2, 2000), (3, 3000))
        for e in (
            {"event": "speech_onset", "ts": n * 60.0, "direction": "d", "utterance": n},
            {"event": "utterance", "ts": n * 60.0 + 1, "direction": "d", "utterance": n,
             "send_ms": 50, "ttfa_ms": first - 10, "first_send_ms": first},
        )
    ])
    stats = c.get("/api/calls/conv3").json()["directions"]["d"]["stats"]
    # Hops report their own duration, not the cumulative stamp: the forward leg is
    # the 10 ms after the model, not the whole 2000 ms since speech onset.
    assert stats["first_send_ms"]["median"] == 10
    assert stats["send_ms"]["median"] == 50
    assert stats["ttfa_ms"]["median"] == 1940
    assert stats["total"]["min"] == 1000 and stats["total"]["max"] == 3000


def test_close_utterances_merge_into_one_turn(client):
    """A sentence split across several energy onsets is shown as one turn."""
    c, root = client
    write_events(root, "conv4", [
        {"event": "speech_onset", "ts": 100.0, "direction": "d", "utterance": 1},
        {"event": "transcript", "ts": 100.4, "direction": "d", "utterance": 1,
         "kind": "input", "text": "My internet is not working. Can you"},
        {"event": "utterance", "ts": 103.0, "direction": "d", "utterance": 1,
         "send_ms": 40, "ttfa_ms": 2000, "first_send_ms": 2002},
        {"event": "speech_onset", "ts": 104.0, "direction": "d", "utterance": 2},
        {"event": "transcript", "ts": 104.2, "direction": "d", "utterance": 2,
         "kind": "input", "text": " help me fix that?"},
        # Far enough away to stay separate.
        {"event": "speech_onset", "ts": 140.0, "direction": "d", "utterance": 3},
        {"event": "transcript", "ts": 140.2, "direction": "d", "utterance": 3,
         "kind": "input", "text": "Yes please."},
    ])
    turns = c.get("/api/calls/conv4").json()["directions"]["d"]["utterances"]

    assert len(turns) == 2
    assert turns[0]["source"] == "My internet is not working. Can you help me fix that?"
    assert turns[0]["parts"] == [1, 2]
    # The turn keeps the latency that was actually measured inside it.
    assert turns[0]["first_send_ms"] == 2002
    assert turns[1]["source"] == "Yes please."


def test_summary_splits_model_from_bridge(client):
    c, root = client
    write_events(root, "conv5", [
        {"event": "speech_onset", "ts": 10.0, "direction": "d", "utterance": 1},
        {"event": "utterance", "ts": 13.0, "direction": "d", "utterance": 1,
         "send_ms": 60, "ttfa_ms": 2060, "first_send_ms": 2070},
    ])
    summary = c.get("/api/calls/conv5").json()["summary"]

    model = next(c for c in summary["components"] if c["key"] == "model")
    bridge = next(c for c in summary["components"] if c["key"] == "bridge")
    # No `speech_end` in this call: it predates that stamp. The model figure falls
    # back to the onset-based one and is flagged, because it is not comparable with
    # the after-speech figure a current call reports.
    assert summary["speech_unmeasured"] is True
    assert model["median_ms"] == 2000   # ttfa minus the send buffer
    assert bridge["median_ms"] == 70    # 60 ms buffering in + 10 ms handing out
    assert summary["median_ms"] == 2070
    assert model["share"] > 0.95
    assert not any(c["key"] == "speech" for c in summary["components"])


def test_stale_burst_is_not_charged_to_an_old_utterance(tmp_path):
    """An utterance that never produced output must not absorb a later burst."""
    from bridge.metrics import CallMetrics

    now = [0.0]
    m = CallMetrics("stale", "d", record_dir=str(tmp_path), clock=lambda: now[0])
    loud = b"\x40\x40" * 1600

    m.on_inbound(loud)           # utterance 1 speaks, and never gets a translation
    m.on_model_send()

    now[0] = 30.0                # a long silence, then utterance 2
    m._speaking = False
    m.on_inbound(loud)
    m.on_model_send()

    now[0] = 32.0                # its translation arrives 2 s later
    m.on_model_audio(loud)
    out = m.summary()

    assert out["utterances"] == 2
    # Utterance 1 goes unmeasured rather than reporting a 32 second translation.
    assert max(out["ttfa_ms"]["values"]) < 5000


def test_caller_language_defaults_to_hindi_and_can_be_changed(client, monkeypatch):
    c, root = client
    monkeypatch.setenv("SETTINGS_PATH", os.path.join(root, "settings.json"))
    monkeypatch.delenv("CALLER_LANGUAGE", raising=False)

    body = c.get("/api/settings").json()
    assert body["caller_language"] == "hi"
    assert {"code": "hi", "name": "Hindi"} in body["languages"]

    assert c.put("/api/settings", json={"caller_language": "es"}).json()["caller_language"] == "es"
    assert c.get("/api/settings").json()["caller_language"] == "es"

    # The bridge reads the same file when it opens a translation session.
    from bridge import settings as bridge_settings
    assert bridge_settings.caller_language() == "es"

    assert c.put("/api/settings", json={}).status_code == 400


def test_unknown_conversation_is_404(client):
    c, _ = client
    assert c.get("/api/calls/nope").status_code == 404


def test_rejects_path_traversal(client):
    c, _ = client
    assert c.get("/api/calls/..%2F..%2Fetc").status_code in (400, 404)


def test_pages_and_static_served(client):
    c, _ = client
    assert "Live call" in c.get("/").text
    assert "Latency dashboard" in c.get("/dashboard").text
    assert c.get("/static/console.css").status_code == 200


def test_live_call_exposes_latency_before_it_ends(client):
    """A call still in progress must show its hand-off delay.

    The end-of-call `utterance` row carries every hop, so a replayed recording
    looks fine even when nothing is emitted during the call. This drives the
    bridge through one turn and stops short of `summary()`, which is the only
    way the missing live emit shows up.
    """
    c, root = client
    now = [0.0]
    m = CallMetrics("conv-inflight", "caller-to-agent", record_dir=root,
                    clock=lambda: now[0])
    loud = b"\x40\x40" * 1600
    m.on_inbound(loud)
    now[0] = 0.1
    m.on_model_send()
    now[0] = 2.0
    m.on_model_audio(loud)
    now[0] = 2.01
    m.on_forwarded()
    # No summary(): the call is still up.

    u = c.get("/api/calls/conv-inflight").json()["directions"]["caller-to-agent"]["utterances"][0]
    assert u["first_send_ms"] == 2010
    assert u["total_ms"] == 2010


def test_static_assets_are_not_cached(client):
    """A stale cached console.js silently reverts the UI to an older deploy."""
    c, _ = client
    for path in ("/", "/dashboard", "/static/console.js"):
        assert "no-store" in c.get(path).headers.get("cache-control", "")


def test_metrics_writes_events_file_the_console_can_read(tmp_path):
    """The bridge's writer and the console's reader agree on the file format."""
    m = CallMetrics("conv-live", "caller-to-agent", record_dir=str(tmp_path),
                    clock=iter([0.0, 0.0, 0.1, 2.0, 2.0, 2.01, 2.01]).__next__)
    loud = (b"\x40\x40" * 1600)
    m.on_inbound(loud)          # onset
    m.on_model_send()           # send_ms
    m.on_model_audio(loud)      # ttfa_ms
    m.on_forwarded()            # first_send_ms
    m.summary()

    path = tmp_path / "conv-live" / "events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    kinds = [e["event"] for e in events]
    assert "speech_onset" in kinds and "model_send" in kinds and "summary" in kinds
    assert all("ts" in e and e["conv"] == "conv-live" for e in events)


def _turn(n, ts, *, speech_ms, ttfa_ms, send_ms=60, first_send=None, direction="d"):
    first_send = ttfa_ms + 10 if first_send is None else first_send
    return [
        {"event": "speech_onset", "ts": ts, "direction": direction, "utterance": n},
        {"event": "speech_end", "ts": ts + speech_ms / 1000, "direction": direction,
         "utterance": n, "speech_ms": speech_ms},
        {"event": "utterance", "ts": ts + 9, "direction": direction, "utterance": n,
         "speech_ms": speech_ms, "send_ms": send_ms, "ttfa_ms": ttfa_ms,
         "ttft_ms": ttfa_ms - 40, "first_send_ms": first_send},
    ]


def test_model_latency_is_measured_from_the_end_of_speech(client):
    """A long sentence must not read as a slow model: the onset-based number holds
    the speaker's own pace, and the model leg is what is left after it."""
    c, root = client
    write_events(root, "conv-speed", [
        *_turn(1, 100.0, speech_ms=4000, ttfa_ms=4300),   # long sentence, quick model
        *_turn(2, 130.0, speech_ms=400, ttfa_ms=1900),    # short word, slow model
    ])
    us = c.get("/api/calls/conv-speed").json()["directions"]["d"]["utterances"]
    assert [u["speech_ms"] for u in us] == [4000, 400]
    assert [u["model_ms"] for u in us] == [300, 1500]
    # The onset-based totals would have ranked these the other way round.
    assert us[0]["total_ms"] > us[1]["total_ms"]


def test_model_that_starts_before_the_speaker_stops_is_reported_as_overlap(client):
    c, root = client
    write_events(root, "conv-overlap", _turn(1, 100.0, speech_ms=3000, ttfa_ms=2200))
    u = c.get("/api/calls/conv-overlap").json()["directions"]["d"]["utterances"][0]
    assert u["model_ms"] == -800 and u["overlapped"] is True


def test_stats_report_p95_and_unanswered_turns(client):
    c, root = client
    events = []
    for i in range(1, 21):
        events += _turn(i, 100.0 + i * 30, speech_ms=500, ttfa_ms=1000 + i * 10)
    # Two turns the model never answered: spoken, but no translation ever came back.
    events += [
        {"event": "speech_onset", "ts": 900.0, "direction": "d", "utterance": 21},
        {"event": "utterance", "ts": 909.0, "direction": "d", "utterance": 21},
    ]
    write_events(root, "conv-p95", events)
    body = c.get("/api/calls/conv-p95").json()
    stats = body["directions"]["d"]["stats"]
    assert stats["model_ms"]["p95"] >= stats["model_ms"]["median"]
    assert body["summary"]["unanswered"] == 1
    assert body["summary"]["turns"] == 21
