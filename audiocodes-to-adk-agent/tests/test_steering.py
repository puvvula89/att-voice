import asyncio

from relay.session_record import SessionRecord
from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)
from relay.steering import run_call


def _run(coro):
    return asyncio.run(coro)


class FakeGateway:
    """Emits a scripted caller event sequence; records audio sent to caller."""

    def __init__(self, events):
        self._events = list(events)
        self.sent = []
        self.ended = False

    async def events(self):
        for e in self._events:
            yield e
            await asyncio.sleep(0)

    async def send_audio(self, pcm):
        self.sent.append(pcm)

    async def transfer(self, uri):
        pass

    async def end(self):
        self.ended = True


class FakeAgent:
    """Scriptable agent session. Records opens and audio received."""

    def __init__(self, key, scripted):
        self.key = key
        self._scripted = list(scripted)
        self.opened_with = None
        self.received = []
        self.closed = False

    async def open(self, record):
        self.opened_with = record

    async def send_audio(self, pcm):
        self.received.append(pcm)

    async def events(self):
        for e in self._scripted:
            yield e
            await asyncio.sleep(0)

    async def close(self):
        self.closed = True


def test_greeter_classifies_then_swaps_to_specialist():
    # Greeter greets, then emits an intent; specialist greets-continues and ends.
    greeter = FakeAgent("greeter", [
        AgentTranscript("agent", "How can I help?", True),
        AgentIntent("billing"),
    ])
    billing = FakeAgent("billing", [
        AgentTranscript("agent", "Let's look at your bill", True),
        AgentEnd(),
    ])
    made = {}

    def factory(key, record):
        a = greeter if key == "greeter" else billing
        made[key] = a
        return a

    gateway = FakeGateway([CallerAudio(b"hi"), CallerEnd()])
    record = SessionRecord(session_id="X")

    _run(run_call(gateway, factory, record))

    # Greeter was opened and closed; billing was routed and opened.
    assert greeter.closed is True
    assert billing.opened_with is record
    # Intent recorded; transcripts captured across BOTH agents.
    assert record.intent == "billing"
    assert "How can I help?" in record.transcript_text()
    assert "Let's look at your bill" in record.transcript_text()


def test_unknown_intent_routes_to_default():
    greeter = FakeAgent("greeter", [AgentIntent("garbled")])
    internet = FakeAgent("internet", [AgentEnd()])

    def factory(key, record):
        return greeter if key == "greeter" else internet

    gateway = FakeGateway([CallerEnd()])
    record = SessionRecord(session_id="X")
    _run(run_call(gateway, factory, record))
    assert internet.opened_with is record  # default specialist opened
