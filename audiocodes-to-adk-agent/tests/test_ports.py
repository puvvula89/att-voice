from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)


def test_agent_events_construct():
    assert AgentAudio(b"\x00\x01").pcm == b"\x00\x01"
    t = AgentTranscript(role="agent", text="hi", final=True)
    assert (t.role, t.text, t.final) == ("agent", "hi", True)
    assert AgentIntent(intent="billing").intent == "billing"
    assert isinstance(AgentEnd(), AgentEnd)


def test_caller_events_construct():
    assert CallerAudio(b"abc").pcm == b"abc"
    assert isinstance(CallerEnd(), CallerEnd)
