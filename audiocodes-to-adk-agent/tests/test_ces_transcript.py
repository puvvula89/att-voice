"""CesBidiSession.events() transcript handling — no network, just feed the out queue.

CES streams the user recognition as the whole cumulative utterance and may send it
more than once (interim, then a corrected/extended final). The session must emit
ONE user transcript per utterance (not one bubble per recognition message).
"""
import asyncio
import json

from relay.agent_channels import CesBidiSession
from relay.channels import AgentTranscript, AgentEnd, AgentTurnComplete


def _drain(messages):
    sess = CesBidiSession(app="apps/x")
    for m in messages:
        sess._out.put(json.dumps(m) if m is not None else None)

    async def run():
        return [ev async for ev in sess.events()]

    return asyncio.run(run())


def test_duplicate_user_recognition_emits_single_final():
    # One utterance recognized twice (interim then extended) + the agent reply.
    events = _drain([
        {"recognitionResult": {"transcript": "Yeah I did sign up for it."}},
        {"recognitionResult": {"transcript": "Yeah I did sign up for it. Thank you."}},
        {"sessionOutput": {"text": "You're welcome. Anything else?"}},
        {"sessionOutput": {"turnCompleted": True}},
        None,
    ])
    users = [e for e in events if isinstance(e, AgentTranscript) and e.role == "user"]
    agents = [e for e in events if isinstance(e, AgentTranscript) and e.role == "agent"]

    # Exactly ONE user bubble, carrying the LAST (most complete) recognition.
    assert len(users) == 1
    assert users[0].text == "Yeah I did sign up for it. Thank you."
    assert users[0].final is True
    # User transcript is flushed BEFORE the agent reply.
    assert events.index(users[0]) < events.index(agents[0])
    assert any(isinstance(e, AgentTurnComplete) for e in events)
    assert isinstance(events[-1], AgentEnd)


def test_trailing_user_utterance_without_reply_is_flushed():
    # User speaks, session ends before any agent text — still emit the user turn once.
    events = _drain([
        {"recognitionResult": {"transcript": "Hello"}},
        {"recognitionResult": {"transcript": "Hello there"}},
        {"endSession": True},
    ])
    users = [e for e in events if isinstance(e, AgentTranscript) and e.role == "user"]
    assert len(users) == 1 and users[0].text == "Hello there" and users[0].final is True
    assert isinstance(events[-1], AgentEnd)
