"""Tests for the pure voice-shaping helpers that replaced the HTTP adapter.

These are the jobs the old adapter did, now run in-process in the A2A executor:
pull caller inputs out of the inbound A2A message, mark the turn IVR + attach
sentiment, and collapse the agent's event stream to one speakable line.
"""
from backend.voice_shaping import (
    CHANNEL_MARKER,
    EMPTY_TURN_FALLBACK,
    augment_message,
    extract_tool_inputs,
    sentiment_envelope,
    speakable_reply,
)


# --- sentiment_envelope ------------------------------------------------------

def test_sentiment_envelope_none_is_empty():
    assert sentiment_envelope(None) == ""
    assert sentiment_envelope({}) == ""


def test_sentiment_envelope_label_and_score():
    assert sentiment_envelope({"label": "frustrated", "score": 0.82}) == (
        "[caller_sentiment: label=frustrated; score=0.82]"
    )


def test_sentiment_envelope_label_only():
    assert sentiment_envelope({"label": "calm"}) == "[caller_sentiment: label=calm]"


# --- augment_message ---------------------------------------------------------

def test_augment_appends_ivr_marker():
    out = augment_message("I want a new phone", None)
    assert out.startswith("I want a new phone")
    assert out.endswith(CHANNEL_MARKER)
    assert "caller_sentiment" not in out


def test_augment_includes_sentiment_then_marker():
    out = augment_message("this is broken", {"label": "angry", "score": 0.9})
    assert "this is broken" in out
    assert "[caller_sentiment: label=angry; score=0.90]" in out
    assert out.endswith(CHANNEL_MARKER)


# --- speakable_reply ---------------------------------------------------------

def test_speakable_reply_flattens_model_text():
    events = [{"content": {"role": "model", "parts": [{"text": "Sure, let's do that."}]}}]
    assert speakable_reply(events) == "Sure, let's do that."


def test_speakable_reply_empty_stream_uses_fallback():
    assert speakable_reply([]) == EMPTY_TURN_FALLBACK
    # a stream with only tool/ui events (no model text) also falls back
    events = [{"content": {"role": "model", "parts": [{"functionCall": {"name": "x"}}]}}]
    assert speakable_reply(events) == EMPTY_TURN_FALLBACK


# --- extract_tool_inputs -----------------------------------------------------

def test_extract_reads_metadata_and_text():
    got = extract_tool_inputs(
        "  upgrade my phone  ",
        {
            "customer_id": "C1",
            "session_id": "S1",
            "caller_sentiment_label": "annoyed",
            "caller_sentiment_score": 0.6,
            "correlation_id": "abc",
            "turn": 3,
        },
    )
    assert got["customer_id"] == "C1"
    assert got["session_id"] == "S1"
    assert got["utterance"] == "upgrade my phone"
    assert got["sentiment"] == {"label": "annoyed", "score": 0.6}
    assert got["correlation_id"] == "abc"
    assert got["turn"] == 3


def test_extract_no_sentiment_label_yields_none():
    got = extract_tool_inputs("hi", {"customer_id": "C1", "caller_sentiment_score": 0.6})
    assert got["sentiment"] is None


def test_extract_tolerates_missing_metadata():
    got = extract_tool_inputs("just talk", None)
    assert got["utterance"] == "just talk"
    assert got["customer_id"] is None
    assert got["session_id"] is None
    assert got["sentiment"] is None


def test_extract_handles_none_text():
    got = extract_tool_inputs(None, {"customer_id": "C1"})
    assert got["utterance"] == ""
    assert got["customer_id"] == "C1"
