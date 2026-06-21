from __future__ import annotations

import base64

from relay.ports import AgentAudio, AgentTranscript, AgentIntent, AgentEnd
from relay.session_record import SessionRecord


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
