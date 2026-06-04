from dotenv import load_dotenv
load_dotenv()

import asyncio
import base64
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions import InMemorySessionService
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

from backend.agent import upgrade_agent

app = FastAPI()
_session_service = InMemorySessionService()
APP_NAME = "phone_upgrade"
# Prebuilt Live voice. Override via LIVE_VOICE; "Charon" reads steady and measured.
LIVE_VOICE = os.environ.get("LIVE_VOICE", "Charon")


@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    # create_session is async in ADK 2.x — must be awaited (or use create_session_sync)
    session = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)
    runner = Runner(
        app_name=APP_NAME,
        agent=upgrade_agent,
        session_service=_session_service,
    )
    queue = LiveRequestQueue()
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        # Calmer, steadier voice — helps with the brisk default tempo.
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)
            )
        ),
        # Stream speech-to-text for both sides so the browser can show a transcript.
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )

    # Make the agent speak first: nudge it with a (call_start) signal so it opens
    # with the welcome greeting (see agent INSTRUCTIONS) before the user says anything.
    queue.send_content(
        types.Content(role="user", parts=[types.Part(text="(call_start)")])
    )

    async def upstream():
        """Read browser → agent: audio blobs and user_action clicks."""
        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                if msg["type"] == "audio":
                    pcm = base64.b64decode(msg["data"])
                    queue.send_realtime(types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
                elif msg["type"] == "user_action":
                    text = f'user selected {msg["selection"]}'
                    queue.send_content(
                        types.Content(role="user", parts=[types.Part(text=text)])
                    )
        except WebSocketDisconnect:
            queue.close()

    async def downstream():
        """Read agent → browser: emit ui_event for pending_ui state deltas, plus raw events."""
        async for event in runner.run_live(
            user_id=user_id,
            session_id=session.id,
            live_request_queue=queue,
            run_config=run_config,
        ):
            ended = False
            if event.actions and getattr(event.actions, "state_delta", None):
                delta = event.actions.state_delta
                pending = delta.get("pending_ui")
                if pending:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "ui_event",
                                "stage_intent": pending["stage_intent"],
                                "payload": pending,
                            }
                        )
                    )
                ended = bool(delta.get("call_ended"))

            # Transcripts: deltas arrive with finished=False; a final cumulative
            # chunk arrives with finished=True. The browser appends deltas and
            # replaces on final, so it never double-renders.
            it = getattr(event, "input_transcription", None)
            if it is not None and it.text:
                await websocket.send_text(json.dumps(
                    {"type": "transcript", "role": "user", "text": it.text, "final": bool(it.finished)}
                ))
            ot = getattr(event, "output_transcription", None)
            if ot is not None and ot.text:
                await websocket.send_text(json.dumps(
                    {"type": "transcript", "role": "agent", "text": ot.text, "final": bool(ot.finished)}
                ))

            await websocket.send_text(
                event.model_dump_json(exclude_none=True, by_alias=True)
            )
            if ended:
                # Agent ended the call. The goodbye audio already streamed in earlier
                # events (buffered for playback); tell the browser, then close.
                await websocket.send_text(json.dumps({"type": "session_end"}))
                queue.close()
                break
        try:
            await websocket.close()
        except Exception:
            pass

    await asyncio.gather(upstream(), downstream())
