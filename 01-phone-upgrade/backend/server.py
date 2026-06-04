from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

APP_NAME = "phone_upgrade"
# Topology toggle: if AGENT_ENGINE_NAME is set, the relay proxies to the agent
# running on Vertex AI Agent Engine (Topology B). Otherwise it runs the agent
# in-process via run_live (Topology A).
AGENT_ENGINE_NAME = os.environ.get("AGENT_ENGINE_NAME")
LIVE_VOICE = os.environ.get("LIVE_VOICE", "Charon")

# Pre-import the Vertex client at module load (proxy mode) so the first
# WebSocket doesn't stall on a cold import → fewer cold-start 503s. Guarded so
# Topology A (local run_live) still works without google-cloud-aiplatform.
try:
    import vertexai as _vertexai
except ImportError:
    _vertexai = None

app = FastAPI()


async def _emit_event(websocket: WebSocket, ev: dict):
    """Translate one (by_alias) ADK event dict into the browser wire protocol:
    a ui_event for a pending_ui state delta, transcript messages, and the raw
    event (for audio playback). Returns True if the agent ended the call."""
    actions = ev.get("actions") or {}
    delta = actions.get("stateDelta") or actions.get("state_delta") or {}

    pending = delta.get("pending_ui")
    if pending:
        await websocket.send_text(json.dumps(
            {"type": "ui_event", "stage_intent": pending["stage_intent"], "payload": pending}
        ))

    # Transcripts stream as deltas (finished=False) then one cumulative final.
    for key, role in (
        ("inputTranscription", "user"), ("input_transcription", "user"),
        ("outputTranscription", "agent"), ("output_transcription", "agent"),
    ):
        tr = ev.get(key)
        if tr and tr.get("text"):
            await websocket.send_text(json.dumps(
                {"type": "transcript", "role": role, "text": tr["text"], "final": bool(tr.get("finished"))}
            ))

    # Forward the raw event (carries audio inlineData the browser plays).
    await websocket.send_text(json.dumps(ev))
    return bool(delta.get("call_ended"))


# Shared across local connections so reconnecting with the same session_id
# resumes within this process (in-memory only — real persistence is the deployed
# VertexAiSessionService path; see agent_app.py).
_local_session_service = None


async def _serve_local(websocket: WebSocket, user_id: str, session_id: str | None):
    """Topology A: run the agent in this process via run_live."""
    import base64
    from google.adk.runners import Runner
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.sessions import InMemorySessionService
    from google.adk.agents.live_request_queue import LiveRequestQueue
    from google.genai import types
    from backend.agent import upgrade_agent

    global _local_session_service
    if _local_session_service is None:
        _local_session_service = InMemorySessionService()
    session_service = _local_session_service

    session = None
    if session_id:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    resumed = session is not None
    if session is None:
        session = await session_service.create_session(app_name=APP_NAME, user_id=user_id)
    await websocket.send_text(json.dumps({
        "type": "session_info", "session_id": session.id, "resumed": resumed,
        "pending_ui": (session.state or {}).get("pending_ui") if resumed else None,
    }))

    runner = Runner(app_name=APP_NAME, agent=upgrade_agent, session_service=session_service)
    queue = LiveRequestQueue()
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE)
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )
    nudge = "(call_resume)" if resumed else "(call_start)"
    queue.send_content(types.Content(role="user", parts=[types.Part(text=nudge)]))

    async def upstream():
        try:
            while True:
                msg = json.loads(await websocket.receive_text())
                if msg["type"] == "audio":
                    pcm = base64.b64decode(msg["data"])
                    queue.send_realtime(types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
                elif msg["type"] == "user_action":
                    queue.send_content(types.Content(
                        role="user", parts=[types.Part(text=f'user selected {msg["selection"]}')]))
        except WebSocketDisconnect:
            queue.close()

    async def downstream():
        async for event in runner.run_live(
            user_id=user_id, session_id=session.id,
            live_request_queue=queue, run_config=run_config,
        ):
            ended = await _emit_event(
                websocket, event.model_dump(exclude_none=True, by_alias=True, mode="json"))
            if ended:
                await websocket.send_text(json.dumps({"type": "session_end"}))
                queue.close()
                break
        try:
            await websocket.close()
        except Exception:
            pass

    await asyncio.gather(upstream(), downstream())


async def _serve_agent_engine(websocket: WebSocket, user_id: str, session_id: str | None):
    """Topology B: proxy browser <-> agent on Vertex AI Agent Engine."""
    vertexai = _vertexai or __import__("vertexai")

    client = vertexai.Client(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    async with client.aio.live.agent_engines.connect(
        agent_engine=AGENT_ENGINE_NAME,
        config={"class_method": "bidi_stream_query", "include_all_fields": True},
    ) as conn:
        # First message sets up (resume or create) the session inside the AE app.
        await conn.send({"user_id": user_id, "session_id": session_id})

        async def upstream():
            try:
                while True:
                    msg = json.loads(await websocket.receive_text())
                    if msg["type"] == "audio":
                        await conn.send({"type": "audio", "data": msg["data"]})
                    elif msg["type"] == "user_action":
                        await conn.send({"type": "user_action", "selection": msg["selection"]})
            except WebSocketDisconnect:
                try:
                    await conn.send({"type": "end"})
                except Exception:
                    pass

        async def downstream():
            while True:
                try:
                    resp = await conn.receive()
                except Exception:
                    break
                if not resp:
                    break
                ev = resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}
                if not isinstance(ev, dict):
                    continue
                if ev.get("type") == "session_info":
                    await websocket.send_text(json.dumps(ev))  # forward control msg as-is
                    continue
                ended = await _emit_event(websocket, ev)
                if ended:
                    await websocket.send_text(json.dumps({"type": "session_end"}))
                    break
            try:
                await websocket.close()
            except Exception:
                pass

        await asyncio.gather(upstream(), downstream())


@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    # Opening frame carries the session_id to resume (or null for a fresh
    # session). Tolerate an old client that doesn't send one.
    session_id = None
    try:
        hello = json.loads(await websocket.receive_text())
        if hello.get("type") == "start":
            session_id = hello.get("session_id")
    except Exception:
        pass
    if AGENT_ENGINE_NAME:
        await _serve_agent_engine(websocket, user_id, session_id)
    else:
        await _serve_local(websocket, user_id, session_id)
