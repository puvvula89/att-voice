"""`MediaGateway` implementations — the caller-side media channel.

Phase 1: `BrowserGateway` over a browser WebSocket (mic in 16k, speaker out 24k).
Phase 2: `AudioCodesGateway` over the AudioCodes VoiceAI Connect Bot API WS — a
real phone call. Same `MediaGateway` port, so the relay core (`run_call`) and the
observe bridge are untouched.
"""
from __future__ import annotations

import base64
import json
import logging

log = logging.getLogger("audiocodes")

from relay.audio_transcode import (
    AGENT_IN_RATE,
    AGENT_OUT_RATE,
    decode_to_pcm16,
    encode_from_pcm16,
    select_formats,
)
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


class AudioCodesGateway:
    """MediaGateway over the AudioCodes VoiceAI Connect (VAIC) Bot API WebSocket.

    VAIC dials the relay (one WS per call) and speaks the Bot API JSON protocol:

      VAIC -> bot : session.initiate / session.resume, userStream.start/.chunk/.stop,
                    activities (start/dtmf), session.end
      bot -> VAIC : session.accepted, userStream.started/.stopped,
                    playStream.start/.chunk/.stop, activities (hangup)

    Caller audio arrives in the negotiated coder; the agents want 16 kHz PCM16, so
    each chunk is transcoded down. Agent audio is 24 kHz PCM16; it's transcoded to
    the negotiated play coder and streamed back. The *original* 24 kHz agent audio,
    plus transcript/agent frames, are published to the ``bus`` so the existing
    ``/observe`` monitor watches an AudioCodes call with no change (same browser
    frame contract as `BrowserGateway`).

    Lifecycle note: the handshake (session.initiate -> session.accepted, format
    negotiation) runs in :meth:`handshake`, called by the server route *before*
    `run_call`, so the play format is known by the first `send_audio`.
    """

    # VAIC reconnects if the WS just closes; only a `hangup` activity ends the call.
    _HANGUP = {"type": "activities", "activities": [{"type": "event", "name": "hangup"}]}

    def __init__(self, websocket, bus=None):
        self._ws = websocket
        self._bus = bus
        self._user_fmt = None   # caller -> bot coder (session.accepted)
        self._play_fmt = None   # bot -> caller coder (playStream.start)
        self.conversation_id = ""
        self.caller = ""
        self._stream_id = 0
        self._play_open = False
        self._ended = False
        self._play_chunks = 0  # DIAGNOSTIC: agent audio chunks sent on current stream

    # --- handshake ----------------------------------------------------------
    async def handshake(self) -> None:
        """Read session.initiate, negotiate coders, reply session.accepted.

        Tolerates a leading session.resume (reconnect). Raises if the peer closes
        or sends something other than an initiate/resume first.
        """
        while True:
            # DIAGNOSTIC: read the raw ASGI frame so we can log EXACTLY what the
            # peer sends (text vs binary vs disconnect) during validation.
            ev = await self._ws.receive()
            etype = ev.get("type")
            raw = ev.get("text")
            if raw is None and ev.get("bytes") is not None:
                raw = ev["bytes"].decode("utf-8", "replace")
            log.info(
                "[audiocodes] ws frame etype=%s keys=%s preview=%r",
                etype, list(ev.keys()), (raw or "")[:160],
            )
            if etype == "websocket.disconnect":
                raise RuntimeError(f"peer disconnected during handshake code={ev.get('code')}")
            if not raw:
                continue
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "connection.validate":
                # LiveHub's "Validate bot connection configuration" probe — it opens
                # a WS, sends connection.validate, and expects connection.validated
                # (then closes). NOT a real call, so don't proceed to run_call: reply
                # and keep waiting (the validation WS then disconnects cleanly).
                log.info("[audiocodes] connection.validate -> connection.validated")
                await self._send({"type": "connection.validated", "success": True})
                continue
            if mtype in ("session.initiate", "session.resume"):
                self.conversation_id = msg.get("conversationId", self.conversation_id)
                self.caller = msg.get("caller", self.caller)
                supported = msg.get("supportedMediaFormats", []) or []
                self._user_fmt, self._play_fmt = select_formats(supported)
                log.info(
                    "[audiocodes] %s conv=%s caller=%s offered=%s -> in=%s out=%s",
                    mtype, self.conversation_id or "?", self.caller or "?",
                    ",".join(supported) or "-", self._user_fmt.name, self._play_fmt.name,
                )
                await self._send({"type": "session.accepted", "mediaFormat": self._user_fmt.name})
                return
            # Ignore any stray pre-initiate activity; keep waiting for the initiate.
            if mtype is None:
                raise RuntimeError("AudioCodes handshake: peer closed before session.initiate")

    # --- caller -> agent ----------------------------------------------------
    async def events(self):
        from fastapi import WebSocketDisconnect
        chunks = 0
        cbytes = 0
        try:
            while True:
                msg = json.loads(await self._ws.receive_text())
                mtype = msg.get("type")
                if mtype == "userStream.start":
                    log.info("[audiocodes] userStream.start conv=%s", self.conversation_id or "?")
                    chunks = 0
                    cbytes = 0
                    await self._send({"type": "userStream.started"})
                elif mtype == "userStream.chunk":
                    pcm = decode_to_pcm16(
                        base64.b64decode(msg["audioChunk"]), self._user_fmt, AGENT_IN_RATE
                    )
                    chunks += 1
                    cbytes += len(pcm or b"")
                    if chunks == 1 or chunks % 50 == 0:
                        log.info("[audiocodes] userStream.chunk #%d (%d pcm bytes total)", chunks, cbytes)
                    if pcm:
                        yield CallerAudio(pcm)
                elif mtype == "userStream.stop":
                    log.info("[audiocodes] userStream.stop conv=%s chunks=%d bytes=%d",
                             self.conversation_id or "?", chunks, cbytes)
                    await self._send({"type": "userStream.stopped"})
                elif mtype == "session.resume":
                    # Reconnect: re-accept on the same negotiated coder.
                    await self._send({"type": "session.accepted", "mediaFormat": self._user_fmt.name})
                elif mtype == "session.end":
                    log.info("[audiocodes] session.end conv=%s reason=%s",
                             self.conversation_id or "?", msg.get("reason"))
                    yield CallerEnd()
                    return
                else:
                    log.info("[audiocodes] ignored inbound mtype=%s keys=%s",
                             mtype, list(msg.keys()))
                # activities (start/dtmf) and anything else: ignore for now.
        except WebSocketDisconnect:
            log.info("[audiocodes] ws disconnect conv=%s", self.conversation_id or "?")
            yield CallerEnd()
            return

    # --- agent -> caller ----------------------------------------------------
    async def send_audio(self, pcm: bytes) -> None:
        if self._ended:
            return
        if not self._play_open:
            self._stream_id += 1
            log.info("[audiocodes] playStream.start id=%d fmt=%s conv=%s",
                     self._stream_id, self._play_fmt.name, self.conversation_id or "?")
            await self._send({
                "type": "playStream.start",
                "streamId": str(self._stream_id),
                "mediaFormat": self._play_fmt.name,
            })
            self._play_open = True
            self._play_chunks = 0
        chunk = encode_from_pcm16(pcm, AGENT_OUT_RATE, self._play_fmt)
        self._play_chunks += 1
        if self._play_chunks == 1 or self._play_chunks % 50 == 0:
            log.info("[audiocodes] playStream.chunk id=%d #%d", self._stream_id, self._play_chunks)
        await self._send({
            "type": "playStream.chunk",
            "streamId": str(self._stream_id),
            "audioChunk": base64.b64encode(chunk).decode("ascii"),
        })
        # Observers hear the agent's native 24 kHz audio (browser plays it at 24k).
        self._observe({"type": "audio", "data": base64.b64encode(pcm).decode("ascii")})

    async def _stop_play(self) -> None:
        if self._play_open:
            log.info("[audiocodes] playStream.stop id=%d chunks=%d conv=%s",
                     self._stream_id, self._play_chunks, self.conversation_id or "?")
            await self._send({"type": "playStream.stop", "streamId": str(self._stream_id)})
            self._play_open = False

    async def end_turn(self) -> None:
        # Agent finished speaking -> close the playStream so VAIC knows the bot
        # stopped talking and resumes forwarding the caller's userStream. The next
        # agent turn opens a fresh playStream (new streamId) on its first chunk.
        if not self._ended:
            await self._stop_play()

    async def transfer(self, uri: str) -> None:
        # The agent swap is relay-internal — the phone call stays on the relay, so
        # there's no AudioCodes call transfer. Surface it to observers only.
        self._observe({"type": "transfer", "uri": uri})

    async def transcript(self, role: str, text: str, final: bool) -> None:
        # UI/observer-only; VAIC has no inbound transcript message.
        self._observe({"type": "transcript", "role": role, "text": text, "final": final})

    async def agent_state(self, key: str, display: str) -> None:
        self._observe({"type": "agent", "key": key, "display": display})

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        try:
            await self._stop_play()
            await self._send(self._HANGUP)
        except Exception:
            pass

    # --- internals ----------------------------------------------------------
    async def _send(self, frame: dict) -> None:
        await self._ws.send_text(json.dumps(frame))

    def _observe(self, frame: dict) -> None:
        if self._bus is not None:
            self._bus.publish(frame)
