from __future__ import annotations

import asyncio
import base64
import json
import queue as _queue
import threading
import uuid

import google.auth
import google.auth.transport.requests
import websocket  # websocket-client

from relay.ports import AgentAudio, AgentTranscript, AgentEnd
from relay.session_record import SessionRecord


class CesBidiSession:
    """AgentSession over CX Agent Studio (CES) BidiRunSession WebSocket."""

    def __init__(self, app: str, location: str = "us",
                 input_rate: int = 16000, output_rate: int = 24000):
        self._app = app
        self._location = location
        self._input_rate = input_rate
        self._output_rate = output_rate
        self._ws = None
        self._out: _queue.Queue = _queue.Queue()
        self._thread = None

    def _token(self) -> str:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    async def open(self, record: SessionRecord) -> None:
        session_id = record.session_id or str(uuid.uuid4())
        record.session_id = session_id
        uri = (
            f"wss://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/"
            f"BidiRunSession/locations/{self._location}"
        )
        headers = [f"Authorization: Bearer {self._token()}"]
        config = {
            "config": {
                "session": f"{self._app}/sessions/{session_id}",
                "inputAudioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": self._input_rate,
                },
                "outputAudioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": self._output_rate,
                },
                # Seed prior conversation so the billing agent continues mid-call.
                # NOTE: confirm the Message field names against the ces.v1 proto in
                # Step 3 — adjust if the smoke shows the context is ignored.
                "historicalContexts": [
                    {"author": "USER", "text": record.context_summary()}
                ],
            }
        }

        def on_open(ws):
            ws.send(json.dumps(config))

        def on_message(ws, message):
            self._out.put(message)

        def on_close(ws, *a):
            self._out.put(None)

        self._ws = websocket.WebSocketApp(
            uri, header=headers,
            on_open=on_open, on_message=on_message, on_close=on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is not None:
            msg = {"realtimeInput": {"audio": base64.b64encode(pcm).decode("ascii")}}
            self._ws.send(json.dumps(msg))

    async def events(self):
        loop = asyncio.get_event_loop()
        while True:
            message = await loop.run_in_executor(None, self._out.get)
            if message is None:
                break
            data = json.loads(message)
            out = data.get("sessionOutput") or {}
            rec = data.get("recognitionResult") or {}
            if rec.get("transcript"):
                yield AgentTranscript("user", rec["transcript"], False)
            if out.get("text"):
                yield AgentTranscript("agent", out["text"], bool(out.get("turnCompleted")))
            if out.get("audio"):
                yield AgentAudio(base64.b64decode(out["audio"]))
            if data.get("endSession"):
                break
        yield AgentEnd()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None
