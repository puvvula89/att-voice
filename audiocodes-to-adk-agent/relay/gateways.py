"""`MediaGateway` implementations — the caller-side media channel.

Phase 1: `HarnessGateway` over a browser WebSocket (mic in 16k, speaker out 24k).
Phase 2 adds an `AudioCodesGateway` over the VAIC Bot API WS — same port, so the
relay core is untouched.
"""
from __future__ import annotations

import base64
import json

from relay.ports import CallerAudio, CallerEnd


class HarnessGateway:
    """MediaGateway over a browser WebSocket (mic in 16k, speaker out 24k)."""

    def __init__(self, websocket):
        self._ws = websocket

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
        await self._ws.send_text(json.dumps(
            {"type": "audio", "data": base64.b64encode(pcm).decode("ascii")}
        ))

    async def transfer(self, uri: str) -> None:
        # Phase 1 has no telephony; log only. (Phase 2 AudioCodes implements this.)
        await self._ws.send_text(json.dumps({"type": "transfer", "uri": uri}))

    async def end(self) -> None:
        try:
            await self._ws.send_text(json.dumps({"type": "session_end"}))
        except Exception:
            pass
