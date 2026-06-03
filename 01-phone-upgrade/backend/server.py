import asyncio
import base64
import json

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


@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    # create_session is synchronous in ADK 2.x (returns Session, not a coroutine)
    session = _session_service.create_session(app_name=APP_NAME, user_id=user_id)
    runner = Runner(
        app_name=APP_NAME,
        agent=upgrade_agent,
        session_service=_session_service,
    )
    queue = LiveRequestQueue()
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
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
            if event.actions and getattr(event.actions, "state_delta", None):
                pending = event.actions.state_delta.get("pending_ui")
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
            await websocket.send_text(
                event.model_dump_json(exclude_none=True, by_alias=True)
            )

    await asyncio.gather(upstream(), downstream())
