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
# Chat (text) engine — a SEPARATE Agent Engine sharing the voice session store.
# When set, the relay serves the chat UI at /chat/{user_id} by proxying to its
# async_stream_query op. Independent of the voice topology toggle above.
CHAT_AGENT_ENGINE_NAME = os.environ.get("CHAT_AGENT_ENGINE_NAME")
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

    from backend.session_resolve import resolve_session
    from backend import formatter
    # Identity-anchored resume (same as the deployed AE path): explicit session_id
    # wins, else the user_id's latest session, else fresh.
    session, resumed = await resolve_session(session_service, APP_NAME, user_id, session_id)
    await websocket.send_text(json.dumps({
        "type": "session_info", "session_id": session.id, "resumed": resumed,
        "pending_ui": formatter.resume_pending_ui(session.state) if resumed else None,
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
                elif msg["type"] == "user_message":
                    # Typed turn on the voice channel — a text turn into the Live
                    # session; the reply stays AUDIO (response_modalities), so the
                    # agent talks back. (Client flushes playback for barge-in.)
                    queue.send_content(types.Content(
                        role="user", parts=[types.Part(text=msg["text"])]))
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
                    elif msg["type"] == "user_message":
                        await conn.send({"type": "user_message", "text": msg["text"]})
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


# --- Chat (text) channel ---------------------------------------------------
# Same shared session store as voice (the chat engine is configured with the
# voice engine's SESSION_ENGINE_ID), so a session started in voice resumes here
# by user_id alone — and vice versa.
async def _emit_chat_event(websocket: WebSocket, ev: dict) -> bool:
    """Translate one chat agent event into the browser wire protocol: a ui_event
    for a pending_ui state delta and a transcript for the agent's text reply.
    Returns True if the agent ended the call."""
    actions = ev.get("actions") or {}
    delta = actions.get("stateDelta") or actions.get("state_delta") or {}

    pending = delta.get("pending_ui")
    if pending:
        await websocket.send_text(json.dumps(
            {"type": "ui_event", "stage_intent": pending["stage_intent"], "payload": pending}
        ))

    # Agent text comes back as model content parts (not transcription, as in voice).
    # run_async yields complete (non-partial) events, so send each as a final line.
    content = ev.get("content") or {}
    if content.get("role") == "model" and not ev.get("partial"):
        text = "".join(p.get("text", "") for p in (content.get("parts") or []) if p.get("text"))
        if text.strip():
            await websocket.send_text(json.dumps(
                {"type": "transcript", "role": "agent", "text": text, "final": True}
            ))
    return bool(delta.get("call_ended"))


async def _serve_chat(websocket: WebSocket, user_id: str):
    """Proxy browser <-> chat agent (async_stream_query) one turn at a time."""
    # Create the client + agent PER CONNECTION and keep both referenced for the
    # connection's lifetime. The agent's async httpx client is owned by `client`;
    # if `client` is GC'd (e.g. a cached-agent helper that returns), the next
    # async_stream_query raises "Cannot send a request, as the client has been
    # closed". Holding `client` here keeps it alive.
    vertexai = _vertexai or __import__("vertexai")
    client = vertexai.Client(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    agent = client.agent_engines.get(name=CHAT_AGENT_ENGINE_NAME)
    sid = {"v": None}

    async def run_turn(message: str):
        kwargs = {"user_id": user_id, "message": message}
        if sid["v"]:
            kwargs["session_id"] = sid["v"]
        async for ev in agent.async_stream_query(**kwargs):
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "session_info":
                if ev.get("session_id"):
                    sid["v"] = ev["session_id"]
                await websocket.send_text(json.dumps(ev))  # forward control msg as-is
                continue
            if await _emit_chat_event(websocket, ev):
                await websocket.send_text(json.dumps({"type": "session_end"}))

    # Opening frame from the client, then greet / welcome-back.
    try:
        await websocket.receive_text()  # {type:"start"}
    except Exception:
        return
    await run_turn("(call_start)")
    while True:
        try:
            msg = json.loads(await websocket.receive_text())
        except WebSocketDisconnect:
            break
        except Exception:
            break
        kind = msg.get("type")
        if kind == "user_message":
            await run_turn(msg.get("text", ""))
        elif kind == "user_action":
            await run_turn(f'user selected {msg["selection"]}')
    try:
        await websocket.close()
    except Exception:
        pass


@app.websocket("/chat/{user_id}")
async def chat_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    await _serve_chat(websocket, user_id)


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
