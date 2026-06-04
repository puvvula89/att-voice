"""Agent Engine bidi app wrapping the phone-upgrade Live agent (Topology B).

Stock ``AdkApp`` registers no ``bidi_stream`` op, so we hand-roll one. The app
runs the same ``run_live`` loop the local relay used, but inside Agent Engine:

- ``register_operations`` advertises a ``bidi_stream`` op (requires EXPERIMENTAL
  server mode at deploy time).
- ``bidi_stream_query`` drains a request queue of client messages (audio /
  user_action / control) into a ``LiveRequestQueue``, runs ``run_live``, and
  yields each event serialized (audio + ``actions.state_delta.pending_ui`` +
  transcripts). The relay re-emits these to the browser unchanged.

Heavy imports and agent construction are deferred to ``set_up`` so the pickled
instance stays light and imports resolve inside the AE container. The agent
reaches the MCP data tools via ``MCP_SERVER_URL`` (set as an AE env var).

Client → app message protocol (dicts placed on the request queue):
    {"user_id": "<id>"}                     first message: set up + greet
    {"type": "audio", "data": "<b64 pcm>"}  16 kHz PCM16, base64
    {"type": "user_action", "selection": "<text>"}
    {"type": "end"}                         close the stream
"""
import asyncio
import base64
import os
from typing import Any, AsyncIterable

APP_NAME = "phone_upgrade"


class LiveAgentApp:
    def set_up(self) -> None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from backend.agent import upgrade_agent

        self._session_service = InMemorySessionService()
        self._runner = Runner(
            app_name=APP_NAME,
            agent=upgrade_agent,
            session_service=self._session_service,
        )
        self._voice = os.environ.get("LIVE_VOICE", "Charon")

    def register_operations(self):
        return {"bidi_stream": ["bidi_stream_query"]}

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

    async def bidi_stream_query(
        self, request_queue: "asyncio.Queue[Any]"
    ) -> AsyncIterable[Any]:
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.genai import types

        first = await request_queue.get()
        user_id = (first or {}).get("user_id", "u1")
        session = await self._session_service.create_session(
            app_name=APP_NAME, user_id=user_id
        )
        live_queue = LiveRequestQueue()
        # Greet first: nudge the agent with (call_start) before the user speaks.
        live_queue.send_content(
            types.Content(role="user", parts=[types.Part(text="(call_start)")])
        )

        async def pump():
            """Client → agent: audio blobs and user_action selections."""
            while True:
                msg = await request_queue.get()
                if msg is None:
                    continue
                kind = msg.get("type")
                if kind == "audio":
                    pcm = base64.b64decode(msg["data"])
                    live_queue.send_realtime(
                        types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                    )
                elif kind == "user_action":
                    text = f'user selected {msg["selection"]}'
                    live_queue.send_content(
                        types.Content(role="user", parts=[types.Part(text=text)])
                    )
                elif kind == "end":
                    live_queue.close()
                    return

        pump_task = asyncio.create_task(pump())
        try:
            async for event in self._runner.run_live(
                user_id=user_id,
                session_id=session.id,
                live_request_queue=live_queue,
                run_config=self._run_config(),
            ):
                # JSON-mode dump so audio bytes become base64 and the payload is
                # transport-safe; same shape the browser already parses.
                yield event.model_dump(exclude_none=True, by_alias=True, mode="json")
        finally:
            pump_task.cancel()
            live_queue.close()


# Module-level instance is what gets deployed.
live_agent = LiveAgentApp()
