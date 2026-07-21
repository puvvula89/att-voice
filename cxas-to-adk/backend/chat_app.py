"""Agent Engine app for the phone-upgrade CHAT (text) channel.

Counterpart to ``agent_app.py`` (voice/bidi). Same agent flow, tools, callbacks,
and UI state-staging — only the transport (standard ``async_stream`` instead of
``bidi_stream``) and the model (a text model) differ. Both channels point their
``VertexAiSessionService`` at the SAME ``SESSION_ENGINE_ID`` so a conversation
started in one channel resumes in the other.

Client → app, per call:
    async_stream_query(user_id="<id>", session_id="<id|null>", message="<text>")
    - message="(call_start)" (or empty) is the OPENING turn: the app resolves the
      session by user_id (resume the latest, else create), emits a session_info
      control message, and nudges the agent to greet ((call_start)) or welcome
      back ((call_resume)) — it decides which from whether a session was found.
    - any other message is a normal user turn: run it through the resumed session.

App → client: a session_info dict first, then the agent's events (each a
``model_dump(by_alias)`` carrying text parts and ``actions.state_delta.pending_ui``
— the same shape the relay already translates for the browser).
"""
import os
from typing import Any, AsyncIterable, Optional

APP_NAME = "phone_upgrade"
_CALL_START = "(call_start)"


class ChatAgentApp:
    def set_up(self) -> None:
        from google.adk.runners import Runner
        from google.adk.sessions import VertexAiSessionService
        from backend.agent import build_upgrade_agent, CHAT_INSTRUCTIONS

        # Shared session store across channels — MUST match the voice app's
        # SESSION_ENGINE_ID so list_sessions/get_session see the other channel's
        # sessions. Falls back to this engine's own id (auto-injected) when unset.
        engine_id = (
            os.environ.get("SESSION_ENGINE_ID")
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
        )
        self._session_service = VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            agent_engine_id=engine_id,
        )
        chat_model = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
        self._runner = Runner(
            app_name=APP_NAME,
            agent=build_upgrade_agent(chat_model, CHAT_INSTRUCTIONS),
            session_service=self._session_service,
        )

    def register_operations(self):
        # Standard streaming op (not bidi) — no EXPERIMENTAL server mode needed.
        return {"async_stream": ["async_stream_query"]}

    async def async_stream_query(
        self,
        *,
        user_id: str = "u1",
        session_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> AsyncIterable[Any]:
        from google.genai import types
        from backend.session_resolve import resolve_session
        from backend import formatter

        opening = (not message) or message == _CALL_START

        # Identity-anchored resume: same helper the voice channel uses. On an
        # explicit session_id we resume it; else the user's latest session (which
        # may have been started by voice); else create fresh.
        session, resumed = await resolve_session(
            self._session_service, APP_NAME, user_id, session_id
        )

        # Control message first: lets the client persist session_id and re-show
        # the last screen (pending_ui) when resuming.
        yield {
            "type": "session_info",
            "session_id": session.id,
            "resumed": resumed,
            "pending_ui": formatter.resume_pending_ui(session.state) if resumed else None,
        }

        # Opening turn → nudge the agent (greet vs welcome-back, decided by the
        # resolved session). Normal turn → forward the user's text verbatim.
        text = (("(call_resume)" if resumed else _CALL_START) if opening else message)

        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        ):
            yield event.model_dump(exclude_none=True, by_alias=True, mode="json")


# Module-level instance is what gets deployed.
chat_agent = ChatAgentApp()
