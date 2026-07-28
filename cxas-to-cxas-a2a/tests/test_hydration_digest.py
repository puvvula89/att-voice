"""Digest tests built from a REAL conversation, not an assumed message shape.

The fixture below is the actual chunk structure of conversation
000cd800-e970-400f-a507-5951fe8e7d4f as returned by
AgentServiceClient.get_conversation — a typed opener followed by spoken turns and
an agent transfer.

It exists because the first version of `_text_of` read only `chunk["text"]`. On
this app nearly every turn is SPOKEN, and spoken turns arrive as
`chunk["transcript"]`, so the digest silently reduced a full internet-support
conversation to the single word the customer typed ("hello"). The agent then
asked whether they were calling about "your previous hello". Nothing errored —
which is exactly why this needs a test rather than a code read.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "hydration"))
os.environ.setdefault("CXAS_PROJECT", "test-project")

from server import _condense, _is_meaningful, _text_of


def _chunk_message(role, **chunk):
    return {"role": role, "chunks": [chunk]}


# The real conversation, verbatim in shape.
REAL_CONVERSATION = {
    "turn_count": 3,
    "turns": [
        {"messages": [
            _chunk_message("user", text="hello"),
            _chunk_message("Voice Concierge",
                           transcript="Thanks for calling! How can I help you today?"),
        ]},
        {"messages": [
            _chunk_message("user", transcript="I have an issue with my internet"),
            _chunk_message("Voice Concierge", agent_transfer={
                "target_agent": "…/agents/internet", "display_name": "Internet Support"}),
            _chunk_message("Internet Support",
                           transcript="Have you already tried restarting your modem and router?"),
        ]},
        {"messages": [
            _chunk_message("user", transcript="No I have not tried that"),
            _chunk_message("Internet Support",
                           transcript="Okay, please unplug both devices, wait 30 seconds."),
        ]},
    ],
}


# --- the regression that shipped: spoken turns were invisible ----------------

def test_reads_spoken_turns_not_just_typed_ones():
    assert _text_of(_chunk_message("user", transcript="I have an issue with my internet")) \
        == "I have an issue with my internet"
    assert _text_of(_chunk_message("user", text="hello")) == "hello"


def test_transfer_chunks_contribute_no_text():
    """An agent_transfer chunk carries routing, not speech — it must not leak."""
    assert _text_of(_chunk_message("Voice Concierge", agent_transfer={
        "target_agent": "…/agents/internet", "display_name": "Internet Support"})) == ""


def test_digest_captures_the_whole_conversation():
    out = _condense(REAL_CONVERSATION)
    assert out.found is True
    # Every spoken turn must survive — this was 'Customer: hello' and nothing else.
    assert "issue with my internet" in out.summary
    assert "restarting your modem" in out.summary
    assert "No I have not tried that" in out.summary


def test_topic_is_the_real_problem_not_the_opener():
    """'hello' must never become the topic when a real one exists."""
    out = _condense(REAL_CONVERSATION)
    assert out.topic == "I have an issue with my internet"


def test_roles_are_labelled_from_the_agent_display_name():
    """Role is 'user' or an agent's display name — anything not user is the agent."""
    out = _condense(REAL_CONVERSATION)
    assert "Customer: I have an issue with my internet" in out.summary
    assert "Agent: Okay, please unplug both devices" in out.summary


# --- the "your previous hello" guard ----------------------------------------

def test_thin_conversation_yields_no_topic():
    thin = {"turns": [{"messages": [_chunk_message("user", text="hello")]}]}
    out = _condense(thin)
    assert out.found is True          # there IS history…
    assert out.topic == ""            # …but nothing worth naming back


def test_meaningfulness_filter():
    for junk in ("hello", "Hi there", "Mike", "test", "  HELLO.  "):
        assert not _is_meaningful(junk), junk
    for real in ("I have an issue with my internet", "my bill is wrong again"):
        assert _is_meaningful(real), real


def test_empty_conversation_is_not_found():
    assert _condense({"turns": []}).found is False
