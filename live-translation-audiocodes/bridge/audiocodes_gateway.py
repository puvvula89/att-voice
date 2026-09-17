"""MediaGateway over the AudioCodes VoiceAI Connect (VAIC) Bot API WebSocket.

VAIC dials the bridge (one WS per bot session) and speaks the Bot API JSON protocol:

  VAIC -> bot : connection.validate, session.initiate / session.resume,
                userStream.start/.chunk/.stop, activities, session.end
  bot -> VAIC : connection.validated, session.accepted, userStream.started/.stopped,
                playStream.start/.chunk/.stop, activities (hangup)

Gotchas carried over from the earlier prototype:
- Close the playStream at the end of every utterance. While one is open VAIC
  treats the bot as speaking and withholds the caller's userStream.
- Closing the WebSocket does not end the call (VAIC reconnects with
  session.resume); only a `hangup` activity does.
"""
from __future__ import annotations

import base64
import json
import logging

from bridge.audio_transcode import (
    MODEL_IN_RATE,
    MODEL_OUT_RATE,
    decode_to_pcm16,
    encode_from_pcm16,
    select_formats,
)
from bridge.channels import CallStart, InboundAudio, InboundEnd

log = logging.getLogger("bridge")


class AudioCodesGateway:
    _HANGUP = {"type": "activities", "activities": [{"type": "event", "name": "hangup"}]}

    def __init__(self, websocket):
        self._ws = websocket
        self._user_fmt = None   # caller -> bot coder (session.accepted)
        self._play_fmt = None   # bot -> caller coder (playStream.start)
        self.conversation_id = ""
        self.caller = ""
        self.participant = ""
        self._stream_id = 0
        self._play_open = False
        self._ended = False
        self._rx_chunks = 0
        self._rx_bytes = 0

    # --- handshake ----------------------------------------------------------
    async def handshake(self) -> bool:
        """Negotiate coders and reply session.accepted.

        Returns False for a validation-only connection (connection.validate,
        then close), True once a real session is accepted.
        """
        while True:
            ev = await self._ws.receive()
            if ev.get("type") == "websocket.disconnect":
                return False
            raw = ev.get("text")
            if raw is None and ev.get("bytes") is not None:
                raw = ev["bytes"].decode("utf-8", "replace")
            if not raw:
                continue
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "connection.validate":
                await self._send({"type": "connection.validated", "success": True})
                continue
            if mtype in ("session.initiate", "session.resume"):
                self.conversation_id = msg.get("conversationId", self.conversation_id)
                self.caller = msg.get("caller", self.caller)
                self.bot_name = msg.get("botName", getattr(self, "bot_name", ""))
                supported = msg.get("supportedMediaFormats", []) or []
                self._user_fmt, self._play_fmt = select_formats(supported)
                log.info(
                    "%s conv=%s offered=%s in=%s out=%s",
                    mtype, self.conversation_id or "?", ",".join(supported) or "-",
                    self._user_fmt.name, self._play_fmt.name,
                )
                await self._send({"type": "session.accepted", "mediaFormat": self._user_fmt.name})
                return True

    # --- inbound ------------------------------------------------------------
    async def events(self):
        from fastapi import WebSocketDisconnect
        try:
            while True:
                msg = json.loads(await self._ws.receive_text())
                mtype = msg.get("type")
                if mtype != "userStream.chunk":
                    log.info("inbound-raw %s", {k: v for k, v in msg.items() if k != "audioChunk"})
                if mtype == "userStream.start":
                    self.participant = msg.get("participant", self.participant)
                    await self._send({"type": "userStream.started"})
                elif mtype == "userStream.chunk":
                    pcm = decode_to_pcm16(
                        base64.b64decode(msg["audioChunk"]), self._user_fmt, MODEL_IN_RATE
                    )
                    self._rx_chunks += 1
                    self._rx_bytes += len(pcm or b"")
                    if pcm:
                        yield InboundAudio(pcm, msg.get("participant", self.participant))
                elif mtype == "userStream.stop":
                    log.info("userStream chunks=%d bytes=%d", self._rx_chunks, self._rx_bytes)
                    self._rx_chunks = self._rx_bytes = 0
                    await self._send({"type": "userStream.stopped"})
                elif mtype == "session.resume":
                    await self._send({"type": "session.accepted", "mediaFormat": self._user_fmt.name})
                elif mtype == "session.end":
                    log.info("session.end conv=%s reason=%s", self.conversation_id or "?", msg.get("reason"))
                    yield InboundEnd()
                    return
                elif mtype == "activities" and any(
                    a.get("name") == "start" for a in msg.get("activities", [])
                ):
                    start = next(a for a in msg["activities"] if a.get("name") == "start")
                    log.info("call start conv=%s", self.conversation_id or "?")
                    yield CallStart(start.get("parameters", {}) or {})
                else:
                    detail = [
                        {k: a.get(k) for k in ("type", "name", "parameters") if k in a}
                        for a in msg.get("activities", [])
                    ]
                    log.info("inbound %s %s conv=%s", mtype, detail, self.conversation_id or "?")
        except WebSocketDisconnect:
            yield InboundEnd()
            return

    # --- outbound -----------------------------------------------------------
    async def configure_session(self) -> None:
        """Keep caller audio flowing while translated audio plays (PRD §7.3).

        Without barge-in VAIC stops the userStream for the duration of every
        playStream, so speech overlapping the translation is never received.
        """
        await self._send({
            "type": "activities",
            "activities": [{
                "type": "event",
                "name": "config",
                "sessionParams": {"bargeIn": True, "userNoInputGiveUpTimeoutMS": 0},
            }],
        })

    @property
    def playing(self) -> bool:
        return self._play_open

    async def send_audio(self, pcm: bytes) -> None:
        if self._ended:
            return
        if not self._play_open:
            self._stream_id += 1
            await self._send({
                "type": "playStream.start",
                "streamId": str(self._stream_id),
                "mediaFormat": self._play_fmt.name,
            })
            self._play_open = True
        chunk = encode_from_pcm16(pcm, MODEL_OUT_RATE, self._play_fmt)
        await self._send({
            "type": "playStream.chunk",
            "streamId": str(self._stream_id),
            "audioChunk": base64.b64encode(chunk).decode("ascii"),
        })

    async def _stop_play(self) -> None:
        if self._play_open:
            await self._send({"type": "playStream.stop", "streamId": str(self._stream_id)})
            self._play_open = False

    async def end_turn(self) -> None:
        if not self._ended:
            await self._stop_play()

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        try:
            await self._stop_play()
            await self._send(self._HANGUP)
        except Exception:
            pass

    async def _send(self, frame: dict) -> None:
        if frame["type"] != "playStream.chunk":
            log.info("outbound %s conv=%s", {k: v for k, v in frame.items() if k != "audioChunk"},
                     self.conversation_id or "?")
        await self._ws.send_text(json.dumps(frame))
