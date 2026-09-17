"""Protocol tests for AudioCodesGateway against a scripted fake VoiceAI Connect peer."""
import array
import asyncio
import base64
import json

from fastapi import WebSocketDisconnect

from bridge.audiocodes_gateway import AudioCodesGateway
from bridge.channels import InboundAudio, InboundEnd


def _run(coro):
    return asyncio.run(coro)


def _pcm(samples):
    return array.array("h", samples).tobytes()


class FakeWS:
    def __init__(self, incoming):
        self._incoming = [json.dumps(m) for m in incoming]
        self.sent = []

    async def receive_text(self):
        if not self._incoming:
            raise WebSocketDisconnect()
        return self._incoming.pop(0)

    async def receive(self):
        if not self._incoming:
            return {"type": "websocket.disconnect", "code": 1000}
        return {"type": "websocket.receive", "text": self._incoming.pop(0)}

    async def send_text(self, s):
        self.sent.append(json.loads(s))


def _types(ws):
    return [f["type"] for f in ws.sent]


def _accepted(formats=("raw/lpcm16", "raw/lpcm16_24"), **extra):
    ws = FakeWS([{"type": "session.initiate", "supportedMediaFormats": list(formats), **extra}])
    gw = AudioCodesGateway(ws)
    assert _run(gw.handshake()) is True
    return ws, gw


def test_handshake_negotiates_native_coders():
    ws, gw = _accepted(("raw/mulaw", "raw/lpcm16", "raw/lpcm16_24"),
                       conversationId="conv-1", caller="+15551234567")
    assert gw.conversation_id == "conv-1"
    assert ws.sent == [{"type": "session.accepted", "mediaFormat": "raw/lpcm16"}]
    assert gw._play_fmt.name == "raw/lpcm16_24"


def test_validation_only_connection_returns_false():
    ws = FakeWS([{"type": "connection.validate"}])
    gw = AudioCodesGateway(ws)
    assert _run(gw.handshake()) is False
    assert ws.sent == [{"type": "connection.validated", "success": True}]


def test_userstream_yields_audio_with_participant():
    pcm16 = _pcm([0, 1000, -1000, 2000])
    ws = FakeWS([
        {"type": "session.initiate", "supportedMediaFormats": ["raw/lpcm16"]},
        {"type": "userStream.start", "participant": "caller"},
        {"type": "userStream.chunk", "audioChunk": base64.b64encode(pcm16).decode()},
        {"type": "userStream.stop"},
        {"type": "session.end", "reason": "Client Side"},
    ])
    gw = AudioCodesGateway(ws)
    _run(gw.handshake())

    async def drain():
        return [ev async for ev in gw.events()]

    events = _run(drain())
    audio = [e for e in events if isinstance(e, InboundAudio)]
    assert len(audio) == 1 and audio[0].pcm == pcm16 and audio[0].participant == "caller"
    assert isinstance(events[-1], InboundEnd)
    assert "userStream.started" in _types(ws) and "userStream.stopped" in _types(ws)


def test_end_turn_stops_playstream_and_next_turn_reopens():
    ws, gw = _accepted(("raw/lpcm16_24",))
    pcm24 = _pcm([0, 100, -100] * 8)
    _run(gw.send_audio(pcm24))
    _run(gw.send_audio(pcm24))
    _run(gw.end_turn())
    _run(gw.send_audio(pcm24))
    _run(gw.end_turn())
    _run(gw.end_turn())  # no-op when nothing is playing

    assert _types(ws).count("playStream.start") == 2
    assert _types(ws).count("playStream.stop") == 2
    starts = [f for f in ws.sent if f["type"] == "playStream.start"]
    assert [s["streamId"] for s in starts] == ["1", "2"]
    chunk = next(f for f in ws.sent if f["type"] == "playStream.chunk")
    assert base64.b64decode(chunk["audioChunk"]) == pcm24


def test_disconnect_yields_end():
    ws, gw = _accepted()

    async def drain():
        return [ev async for ev in gw.events()]

    events = _run(drain())
    assert len(events) == 1 and isinstance(events[0], InboundEnd)


def test_end_stops_play_and_hangs_up_once():
    ws, gw = _accepted()
    _run(gw.send_audio(_pcm([0] * 240)))
    _run(gw.end())
    assert _types(ws)[-2:] == ["playStream.stop", "activities"]
    assert ws.sent[-1]["activities"][0]["name"] == "hangup"
    n = len(ws.sent)
    _run(gw.end())
    assert len(ws.sent) == n
