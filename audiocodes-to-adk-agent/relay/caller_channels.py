"""`MediaGateway` implementations — the caller-side media channel.

Phase 1: `BrowserGateway` over a browser WebSocket (mic in 16k, speaker out 24k).
Phase 2 adds an `AudioCodesGateway` over the VAIC Bot API WS — same port, so the
relay core is untouched.
"""
from __future__ import annotations

import base64
import json

from relay.channels import CallerAudio, CallerEnd


class BrowserGateway:
    """MediaGateway over a browser WebSocket (mic in 16k, speaker out 24k).

    If a ``bus`` (CallBus) is given, every outgoing caller frame is also published
    to it so read-only observers (the /audiocodes monitor) can watch the call.
    """

    def __init__(self, websocket, bus=None):
        self._ws = websocket
        self._bus = bus

    async def _emit(self, frame: dict) -> None:
        await self._ws.send_text(json.dumps(frame))
        if self._bus is not None:
            self._bus.publish(frame)

    async def events(self):
        from fastapi import WebSocketDisconnect
        try:
            while True:
                msg = json.loads(await self._ws.receive_text())
                if msg.get("type") == "audio":
                    yield CallerAudio(base64.b64decode(msg["data"]))
                elif msg.get("type") == "end":
                    yield CallerEnd()
                    return
        except WebSocketDisconnect:
            yield CallerEnd()
            return

    async def send_audio(self, pcm: bytes) -> None:
        await self._emit(
            {"type": "audio", "data": base64.b64encode(pcm).decode("ascii")}
        )

    async def transfer(self, uri: str) -> None:
        # Phase 1 has no telephony; log only. (Phase 2 AudioCodes implements this.)
        await self._emit({"type": "transfer", "uri": uri})

    async def transcript(self, role: str, text: str, final: bool) -> None:
        # Live transcript for the demo UI. Deltas (final=False) then one cumulative
        # final (final=True) per utterance — the client appends deltas, replaces on
        # final. Display-only; the relay still records final turns on the record.
        await self._emit(
            {"type": "transcript", "role": role, "text": text, "final": final}
        )

    async def agent_state(self, key: str, display: str) -> None:
        # Which specialist is live now (greeter -> specialist). Drives the UI's
        # agent-indicator badge. Emitted whenever an agent activates.
        await self._emit({"type": "agent", "key": key, "display": display})

    async def end(self) -> None:
        try:
            await self._ws.send_text(json.dumps({"type": "session_end"}))
        except Exception:
            pass
