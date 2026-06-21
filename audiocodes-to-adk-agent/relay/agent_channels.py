"""`AgentSession` implementations — one per back-end platform — plus the factory.

Each class is a drop-in behind the `AgentSession` port (relay/channels.py); the relay
core (steering loop) is identical regardless of which one is active:

- `AdkLiveSession`  — ADK `run_live` in-process (local dev).
- `AeAdkSession`    — ADK agent deployed on Agent Engine (`bidi_stream_query`).
- `CesBidiSession`  — CX Agent Studio (CES) `BidiRunSession` WebSocket.

`make_factory` returns `agent_factory(key, record) -> AgentSession`, picking the
impl by agent key and environment (in-process vs Agent Engine).

Heavy / optional deps (google.adk, vertexai) are imported lazily inside methods so
importing this module stays cheap and a path that uses only one back-end doesn't
pay for the others.
"""
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

from relay.channels import AgentAudio, AgentTranscript, AgentIntent, AgentEnd
from relay.call_session import SessionRecord
from agents.registry import ADK_AGENTS

APP_NAME = "att_steering"


# --------------------------------------------------------------------------- #
# ADK in-process (run_live / Gemini Live)                                      #
# --------------------------------------------------------------------------- #
class AdkLiveSession:
    """AgentSession over ADK run_live (Gemini Live). One per agent activation.

    All AdkLiveSessions in a call share the SAME session_service + session_id, so a
    specialist inherits the greeter's turns (ADK shared session).
    """

    def __init__(self, agent, session_service, voice: str = "Charon"):
        self._agent = agent
        self._session_service = session_service
        self._voice = voice
        self._queue = None
        self._session_id = None
        self._user_id = "caller"

    def _run_config(self):
        from google.adk.agents.run_config import RunConfig, StreamingMode
        from google.genai import types
        return RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def open(self, record: SessionRecord) -> None:
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.genai import types
        from relay.call_session import resolve_session

        # Greeter starts a fresh session each call; specialists resume THIS call's
        # session (the id the greeter set on the record) for the seamless handoff.
        # Never resume a prior call's session — replaying its history breaks run_live.
        self._user_id = record.caller or "caller"
        if self._agent.name == "greeter":
            session = await self._session_service.create_session(
                app_name=APP_NAME, user_id=self._user_id
            )
        else:
            session, _ = await resolve_session(
                self._session_service, APP_NAME, self._user_id, record.session_id
            )
        self._session_id = session.id
        record.session_id = session.id
        self._queue = LiveRequestQueue()
        # Greeter is told (call_start); specialists are told (handoff) so they
        # continue WITHOUT re-greeting (reinforced by their instructions).
        nudge = "(call_start)" if self._agent.name == "greeter" else "(handoff)"
        self._queue.send_content(
            types.Content(role="user", parts=[types.Part(text=nudge)])
        )

    async def send_audio(self, pcm: bytes) -> None:
        from google.genai import types
        if self._queue is not None:
            self._queue.send_realtime(
                types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
            )

    async def events(self):
        from google.adk.runners import Runner
        runner = Runner(
            app_name=APP_NAME, agent=self._agent, session_service=self._session_service
        )
        async for event in runner.run_live(
            user_id=self._user_id,
            session_id=self._session_id,
            live_request_queue=self._queue,
            run_config=self._run_config(),
        ):
            ev = event.model_dump(exclude_none=True, by_alias=True, mode="json")

            # Intent staged by the greeter's after_tool_callback.
            actions = ev.get("actions") or {}
            delta = actions.get("stateDelta") or actions.get("state_delta") or {}
            if delta.get("intent"):
                yield AgentIntent(delta["intent"])

            # Transcripts (deltas then a cumulative final).
            for key, role in (
                ("inputTranscription", "user"), ("input_transcription", "user"),
                ("outputTranscription", "agent"), ("output_transcription", "agent"),
            ):
                tr = ev.get(key)
                if tr and tr.get("text"):
                    yield AgentTranscript(role, tr["text"], bool(tr.get("finished")))

            # Audio (base64 inline_data in content parts).
            content = ev.get("content") or {}
            for part in content.get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    b64 = inline["data"].replace("-", "+").replace("_", "/")
                    yield AgentAudio(base64.b64decode(b64))

        yield AgentEnd()

    async def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None


# --------------------------------------------------------------------------- #
# ADK on Agent Engine (bidi_stream_query)                                      #
# --------------------------------------------------------------------------- #
class AeAdkSession:
    """AgentSession over an ADK agent deployed on Agent Engine (bidi_stream_query)."""

    def __init__(self, engine: str, agent_key: str, project: str,
                 location: str = "us-central1"):
        self._engine = engine
        self._agent_key = agent_key
        self._project = project
        self._location = location
        self._client = None
        self._cm = None
        self._conn = None
        self._record = None

    async def open(self, record: SessionRecord) -> None:
        import vertexai
        self._record = record
        # Hold the Client for the whole connection (GC closes its httpx client).
        self._client = vertexai.Client(project=self._project, location=self._location)
        self._cm = self._client.aio.live.agent_engines.connect(
            agent_engine=self._engine,
            config={"class_method": "bidi_stream_query", "include_all_fields": True},
        )
        self._conn = await self._cm.__aenter__()
        await self._conn.send({
            "user_id": record.caller or "caller",
            "session_id": record.session_id,
            "agent_key": self._agent_key,
        })

    async def send_audio(self, pcm: bytes) -> None:
        if self._conn is not None:
            await self._conn.send(
                {"type": "audio", "data": base64.b64encode(pcm).decode("ascii")}
            )

    async def events(self):
        while True:
            try:
                resp = await self._conn.receive()
            except Exception:
                break
            if not resp:
                break
            ev = resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "session_info":
                if ev.get("session_id"):
                    self._record.session_id = ev["session_id"]  # share across agents
                continue
            actions = ev.get("actions") or {}
            delta = actions.get("stateDelta") or actions.get("state_delta") or {}
            if delta.get("intent"):
                yield AgentIntent(delta["intent"])
            for key, role in (
                ("inputTranscription", "user"), ("input_transcription", "user"),
                ("outputTranscription", "agent"), ("output_transcription", "agent"),
            ):
                tr = ev.get(key)
                if tr and tr.get("text"):
                    yield AgentTranscript(role, tr["text"], bool(tr.get("finished")))
            content = ev.get("content") or {}
            for part in content.get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    b64 = inline["data"].replace("-", "+").replace("_", "/")
                    yield AgentAudio(base64.b64decode(b64))
        yield AgentEnd()

    async def close(self) -> None:
        try:
            if self._conn is not None:
                await self._conn.send({"type": "end"})
        except Exception:
            pass
        try:
            if self._cm is not None:
                await self._cm.__aexit__(None, None, None)
        finally:
            self._cm = None
            self._conn = None
            self._client = None


# --------------------------------------------------------------------------- #
# CES (CX Agent Studio) BidiRunSession                                         #
# --------------------------------------------------------------------------- #
def _ces_handoff_nudge(record) -> str:
    """Text turn that triggers CES's first response at handoff.

    Use the caller's most substantive utterance (longest user turn) so the
    specialist answers the actual question directly; fall back to an intent-based
    line if no turns were captured. Avoids picking short confirmations like "yes".
    """
    user_turns = [t.text for t in getattr(record, "turns", []) if t.role == "user" and t.text]
    if user_turns:
        return max(user_turns, key=len)
    return f"I need help with {getattr(record, 'intent', None) or 'my account'}."


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
        self._connected = threading.Event()

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
                # historical_contexts is a repeated ces.v1.Message: {role, chunks[]}
                # where each Chunk carries text. (A bare {author,text} is rejected and
                # the bidi session times out with FAILED_PRECONDITION.)
                "historicalContexts": [
                    {"role": "user", "chunks": [{"text": record.context_summary()}]}
                ],
            }
        }

        def on_open(ws):
            ws.send(json.dumps(config))
            self._connected.set()

        def on_message(ws, message):
            self._out.put(message)

        def on_close(ws, *a):
            self._connected.set()  # unblock open() even on failed connect
            self._out.put(None)

        self._ws = websocket.WebSocketApp(
            uri, header=headers,
            on_open=on_open, on_message=on_message, on_close=on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()
        # Wait until the socket is open and config is sent, so the first audio
        # frames aren't dropped against a not-yet-connected socket (which would
        # leave CES with no input and time the session out after 30s).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._connected.wait, 15)
        # CES bidi is REACTIVE — after a greeter→specialist handoff it stays
        # silent until it gets live input (it only speaks after VAD end-of-speech
        # on audio). historicalContexts is just context, not a trigger. So send a
        # text turn to make the specialist take the FIRST turn immediately (the
        # seamless handoff), mirroring the ADK `(handoff)` nudge. CES answers text
        # input directly (verified) and emits NO recognitionResult for it, so it
        # doesn't show up as a spurious caller bubble.
        nudge = _ces_handoff_nudge(record)
        if nudge and self._ws is not None and self._ws.sock is not None:
            try:
                self._ws.send(json.dumps({"realtimeInput": {"text": nudge}}))
            except Exception:
                pass

    async def send_audio(self, pcm: bytes) -> None:
        ws = self._ws
        if ws is None or not self._connected.is_set() or ws.sock is None:
            return
        msg = {"realtimeInput": {"audio": base64.b64encode(pcm).decode("ascii")}}
        try:
            ws.send(json.dumps(msg))
        except websocket.WebSocketConnectionClosedException:
            pass

    async def events(self):
        loop = asyncio.get_running_loop()
        while True:
            message = await loop.run_in_executor(None, self._out.get)
            if message is None:
                break
            data = json.loads(message)
            out = data.get("sessionOutput") or {}
            rec = data.get("recognitionResult") or {}
            # CES sends ONE COMPLETE message per turn, not ADK-style deltas:
            #   recognitionResult.transcript = the full user utterance (post-VAD)
            #   sessionOutput.text           = the full agent turn text (one per turnIndex)
            # `turnCompleted` arrives LATER on a separate audio message, so it must
            # NOT gate text finality. Emit each as final=True so the UI closes the
            # bubble per turn; gating on turnCompleted left every turn appended into
            # one never-closed bubble (user + agent text all mingled).
            if rec.get("transcript"):
                yield AgentTranscript("user", rec["transcript"], True)
            if out.get("text"):
                yield AgentTranscript("agent", out["text"], True)
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


# --------------------------------------------------------------------------- #
# Factory                                                                      #
# --------------------------------------------------------------------------- #
def make_factory(*, session_service=None, ces_app: str, ces_location: str = "us",
                 ae_engine: str = "", project: str = "",
                 ae_location: str = "us-central1", voice: str = "Charon"):
    """Return agent_factory(key, record) -> AgentSession.

    ADK keys -> AeAdkSession when ae_engine is set (agents deployed on Agent
    Engine), else in-process AdkLiveSession (local dev). billing -> CesBidiSession.
    """

    def factory(key, record):
        if key in ADK_AGENTS:
            if ae_engine:
                return AeAdkSession(engine=ae_engine, agent_key=key,
                                    project=project, location=ae_location)
            return AdkLiveSession(ADK_AGENTS[key], session_service, voice=voice)
        if key == "billing":
            return CesBidiSession(app=ces_app, location=ces_location)
        # Unknown key should not happen (router defaults), but fail safe to internet.
        if ae_engine:
            return AeAdkSession(engine=ae_engine, agent_key="internet",
                                project=project, location=ae_location)
        return AdkLiveSession(ADK_AGENTS["internet"], session_service, voice=voice)

    return factory
