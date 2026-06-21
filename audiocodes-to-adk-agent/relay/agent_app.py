from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

APP_NAME = "att_steering"


class SteeringApp:
    """One multi-agent Agent Engine app. Selects the agent per call by agent_key;
    all agents share the engine's session store by session_id (no SESSION_ENGINE_ID)."""

    def set_up(self) -> None:
        from google.adk.sessions import VertexAiSessionService
        from agents.registry import ADK_AGENTS

        engine_id = (
            os.environ.get("SESSION_ENGINE_ID")
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
        )
        self._session_service = VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            agent_engine_id=engine_id,
        )
        self._agents = ADK_AGENTS
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

    async def bidi_stream_query(self, request_queue: "asyncio.Queue[Any]"):
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.adk.runners import Runner
        from google.genai import types
        from relay.session import resolve_session

        first = await request_queue.get()
        user_id = (first or {}).get("user_id", "caller")
        req_sid = (first or {}).get("session_id")
        agent_key = (first or {}).get("agent_key", "greeter")
        agent = self._agents.get(agent_key, self._agents["greeter"])

        session, resumed = await resolve_session(
            self._session_service, APP_NAME, user_id, req_sid
        )
        yield {"type": "session_info", "session_id": session.id, "resumed": resumed}

        live_queue = LiveRequestQueue()
        nudge = "(call_start)" if agent_key == "greeter" else "(handoff)"
        live_queue.send_content(
            types.Content(role="user", parts=[types.Part(text=nudge)])
        )

        async def pump():
            while True:
                msg = await request_queue.get()
                if msg is None:
                    continue
                if msg.get("type") == "audio":
                    pcm = base64.b64decode(msg["data"])
                    live_queue.send_realtime(
                        types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                    )
                elif msg.get("type") == "end":
                    live_queue.close()
                    return

        pump_task = asyncio.create_task(pump())
        runner = Runner(
            app_name=APP_NAME, agent=agent, session_service=self._session_service
        )
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session.id,
                live_request_queue=live_queue,
                run_config=self._run_config(),
            ):
                yield event.model_dump(exclude_none=True, by_alias=True, mode="json")
        finally:
            pump_task.cancel()
            live_queue.close()
