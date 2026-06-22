"""Protocol tests for AudioCodesGateway against a fake VoiceAI Connect peer.

No agents, no network — a scripted fake WebSocket feeds Bot API messages and
captures what the gateway sends back. Verifies the wire protocol (handshake,
coder negotiation, userStream decode, playStream encode, hangup) and that the
observe bus sees browser-shaped frames.
"""
import array
import asyncio
import base64
import json

from fastapi import WebSocketDisconnect

from relay.caller_channels import AudioCodesGateway
from relay.channels import CallerAudio, CallerEnd


def _run(coro):
    return asyncio.run(coro)


def _pcm(samples):
    return array.array("h", samples).tobytes()


class FakeWS:
    """Feeds queued text frames; records sent frames. Disconnects when drained."""

    def __init__(self, incoming, headers=None):
        self._incoming = [json.dumps(m) for m in incoming]
        self.sent = []
        self.headers = headers or {}

    async def receive_text(self):
        if not self._incoming:
            raise WebSocketDisconnect()
        return self._incoming.pop(0)

    async def receive(self):
        # Raw ASGI-style frame, used by handshake()'s diagnostic reader.
        if not self._incoming:
            return {"type": "websocket.disconnect", "code": 1006}
        return {"type": "websocket.receive", "text": self._incoming.pop(0)}

    async def send_text(self, s):
        self.sent.append(json.loads(s))


class FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, frame):
        self.published.append(frame)


def _sent_types(ws):
    return [f["type"] for f in ws.sent]


def test_handshake_negotiates_native_coders_and_accepts():
    ws = FakeWS([{
        "type": "session.initiate",
        "conversationId": "conv-1",
        "caller": "+15551234567",
        "supportedMediaFormats": ["raw/mulaw", "raw/lpcm16", "raw/lpcm16_24"],
    }])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())

    assert gw.conversation_id == "conv-1"
    assert gw.caller == "+15551234567"
    # Accepted on the caller-in coder (16k linear); play coder is the 24k native.
    assert ws.sent == [{"type": "session.accepted", "mediaFormat": "raw/lpcm16"}]
    assert gw._play_fmt.name == "raw/lpcm16_24"


def test_connection_validate_is_acked_then_session_initiate_proceeds():
    # LiveHub validation sends connection.validate first; bot must reply
    # connection.validated, then continue to the real session.initiate handshake.
    ws = FakeWS([
        {"type": "connection.validate"},
        {"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]},
    ])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())
    assert ws.sent == [
        {"type": "connection.validated", "success": True},
        {"type": "session.accepted", "mediaFormat": "raw/lpcm16"},
    ]


def test_userstream_decodes_to_caller_audio_and_acks():
    pcm16 = _pcm([0, 1000, -1000, 2000])
    ws = FakeWS([
        {"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]},
        {"type": "userStream.start"},
        {"type": "userStream.chunk", "audioChunk": base64.b64encode(pcm16).decode()},
        {"type": "userStream.stop"},
        {"type": "session.end", "reason": "Client Side"},
    ])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())

    async def drain():
        out = []
        async for ev in gw.events():
            out.append(ev)
        return out

    events = _run(drain())

    # 16k in = agent rate, so the PCM passes through unchanged.
    audio = [e for e in events if isinstance(e, CallerAudio)]
    assert len(audio) == 1 and audio[0].pcm == pcm16
    assert isinstance(events[-1], CallerEnd)
    # userStream.start/.stop were acked.
    assert "userStream.started" in _sent_types(ws)
    assert "userStream.stopped" in _sent_types(ws)


def test_end_turn_stops_playstream_and_next_turn_reopens():
    # Floor release: after the agent's turn, end_turn() must send playStream.stop
    # so VAIC stops withholding the caller's userStream; the next turn opens a
    # fresh playStream with a new streamId.
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16_24"]}])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())

    pcm24 = _pcm([0, 100, -100] * 8)
    _run(gw.send_audio(pcm24))   # opens playStream id=1
    _run(gw.end_turn())          # closes it (playStream.stop)
    _run(gw.send_audio(pcm24))   # opens a NEW playStream id=2
    _run(gw.end_turn())

    types = _sent_types(ws)
    assert types.count("playStream.start") == 2
    assert types.count("playStream.stop") == 2
    starts = [f for f in ws.sent if f["type"] == "playStream.start"]
    assert starts[0]["streamId"] == "1" and starts[1]["streamId"] == "2"
    # A no-op end_turn (nothing playing) must not emit a stray stop.
    _run(gw.end_turn())
    assert _sent_types(ws).count("playStream.stop") == 2


def test_disconnect_yields_caller_end():
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]}])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())

    async def drain():
        return [ev async for ev in gw.events()]

    events = _run(drain())
    assert len(events) == 1 and isinstance(events[0], CallerEnd)


def test_send_audio_opens_playstream_then_chunks_and_observes():
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16_24"]}])
    bus = FakeBus()
    gw = AudioCodesGateway(ws, bus=bus)
    _run(gw.handshake())

    pcm24 = _pcm([100] * 240)  # 10 ms @ 24k, native -> passes through
    _run(gw.send_audio(pcm24))
    _run(gw.send_audio(pcm24))

    # First send opens the stream; both send a chunk. Only ONE start.
    after_accept = ws.sent[1:]  # drop session.accepted
    assert [f["type"] for f in after_accept] == [
        "playStream.start", "playStream.chunk", "playStream.chunk",
    ]
    start = after_accept[0]
    assert start["mediaFormat"] == "raw/lpcm16_24"
    chunk = after_accept[1]
    assert chunk["streamId"] == start["streamId"]
    assert base64.b64decode(chunk["audioChunk"]) == pcm24  # 24k native, untouched

    # Observers get the original 24k agent audio as a browser audio frame.
    audio_frames = [f for f in bus.published if f["type"] == "audio"]
    assert len(audio_frames) == 2
    assert base64.b64decode(audio_frames[0]["data"]) == pcm24


def test_end_stops_play_and_sends_hangup():
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]}])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())
    _run(gw.send_audio(_pcm([0] * 240)))
    _run(gw.end())

    tail = _sent_types(ws)[-2:]
    assert tail == ["playStream.stop", "activities"]  # stop then hangup activity
    hangup = ws.sent[-1]
    assert hangup["activities"][0]["name"] == "hangup"
    # Idempotent: a second end() is a no-op.
    n = len(ws.sent)
    _run(gw.end())
    assert len(ws.sent) == n


def test_ui_frames_go_to_bus_only_not_to_vaic():
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]}])
    bus = FakeBus()
    gw = AudioCodesGateway(ws, bus=bus)
    _run(gw.handshake())
    n_before = len(ws.sent)

    _run(gw.transcript("user", "hi there", True))
    _run(gw.agent_state("billing", "Billing"))
    _run(gw.transfer("sip:billing@relay"))

    # Nothing extra went to VAIC (it has no inbound transcript/agent/transfer msg).
    assert len(ws.sent) == n_before
    types = [f["type"] for f in bus.published]
    assert types == ["transcript", "agent", "transfer"]
