from __future__ import annotations

import asyncio

from relay.ports import AgentAudio, AgentTranscript, AgentIntent, AgentEnd
from relay.session_record import SessionRecord

APP_NAME = "att_steering"


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
        from relay.session_resolve import resolve_session  # see Step 2 note

        session, _ = await resolve_session(
            self._session_service, APP_NAME, record.caller or "caller", record.session_id
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
            user_id="caller",
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
                    import base64
                    b64 = inline["data"].replace("-", "+").replace("_", "/")
                    yield AgentAudio(base64.b64decode(b64))

        yield AgentEnd()

    async def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None
