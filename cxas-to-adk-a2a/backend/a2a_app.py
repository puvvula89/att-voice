"""A2A serving app for the phone-upgrade CHAT (text) agent on Agent Engine.

Replaces the standalone HTTP adapter: CES now calls this ADK agent DIRECTLY over
the Agent Engine A2A endpoint (RemoteAgentTool, P4SA auth). The three jobs the old
adapter did move in-process here — pull the caller inputs out of the A2A message,
mark the turn as IVR + attach sentiment, and flatten the agent's event stream to
one speakable line — while session resolution reuses the same shared-store helper
the browser/voice channels use, so a conversation started on one channel resumes
on another.

Deployed via the Agent Engine ``A2aAgent`` template (deploy/deploy_chat_engine.py).
The template auto-fills the agent card's interface URL with this engine's ``/a2a``
endpoint at set_up and calls ``build_executor`` once inside the container, so heavy
ADK imports are deferred there (the pickled module stays light).
"""
import logging
import os
from typing import Any, Dict, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import AgentSkill
from vertexai.agent_engines.templates.a2a import A2aAgent, create_agent_card

from backend.voice_shaping import (
    augment_message,
    extract_tool_inputs,
    speakable_reply,
)

APP_NAME = "phone_upgrade"
_CALL_START = "(call_start)"
_log = logging.getLogger("cxas.a2a")

# One structured record per turn — the join key between the CES conversation and
# the ADK session for later analysis (parity with the old adapter's logging).
_ASSOCIATION_LOG = logging.getLogger("cxas.association")


def _log_association(inputs: Dict[str, Any], session_id: Optional[str], *, error: bool = False):
    import json
    import uuid
    _ASSOCIATION_LOG.info(json.dumps({
        "event": "cxas_turn",
        "correlation_id": inputs.get("correlation_id") or uuid.uuid4().hex,
        "customer_id": inputs.get("customer_id"),
        "session_id": session_id,
        "channel": "ivr",
        "turn": inputs.get("turn"),
        "error": error,
        "sentiment": inputs.get("sentiment"),
    }))


class SalesA2aExecutor(AgentExecutor):
    """Runs one IVR turn against the phone-upgrade chat agent and returns one
    speakable A2A message. Built once per container (heavy ADK deps live here)."""

    def __init__(self):
        from google.adk.runners import Runner
        from google.adk.sessions import VertexAiSessionService
        from backend.agent import build_upgrade_agent, CHAT_INSTRUCTIONS

        # Shared session store across channels — MUST match the voice app's
        # SESSION_ENGINE_ID so the other channel's sessions are visible. Falls back
        # to this engine's own id (auto-injected by Agent Engine) when unset.
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

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        from google.genai import types
        from a2a.helpers.proto_helpers import new_text_message
        from backend.session_resolve import resolve_session

        inputs = extract_tool_inputs(context.get_user_input(), _metadata_of(context))
        user_id = inputs["customer_id"] or "u1"
        session_id = None
        try:
            session, resumed = await resolve_session(
                self._session_service, APP_NAME, user_id, inputs["session_id"]
            )
            session_id = session.id

            # Normal turn → caller words + IVR marker + sentiment. Empty turn
            # (rare — CES skips the tool for a pure greeting) → greet / welcome-back
            # nudge, matching the chat channel's opening behavior.
            if inputs["utterance"]:
                text = augment_message(inputs["utterance"], inputs["sentiment"])
            else:
                text = "(call_resume)" if resumed else _CALL_START

            events = []
            async for event in self._runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=text)]),
            ):
                events.append(event.model_dump(exclude_none=True, by_alias=True, mode="json"))

            reply = speakable_reply(events)
            _log_association(inputs, session_id)
        except Exception:
            _log.exception("a2a turn failed")
            _log_association(inputs, session_id, error=True)
            reply = "I'm sorry, I'm having trouble right now. Please hold for a moment."

        # Return the spoken reply; carry the resolved session_id back in metadata so
        # CES can cache it and thread subsequent turns (2-step session resolution).
        msg = new_text_message(reply)
        if session_id:
            msg.metadata = {"session_id": session_id}
        await event_queue.enqueue_event(msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Single-shot request/response turns; nothing to cancel.
        raise Exception("cancel not supported")


def _metadata_of(context: "RequestContext") -> Dict[str, Any]:
    """Best-effort read of the inbound A2A message metadata as a plain dict.

    a2a-sdk 1.x messages are protobuf: ``metadata`` is a ``Struct`` (mapping of
    native values), not a ``dict`` — so we convert rather than isinstance-check.
    """
    msg = getattr(context, "message", None)
    meta = getattr(msg, "metadata", None) if msg is not None else None
    if meta is None:
        return {}
    try:
        return dict(meta)  # works for both dict and protobuf Struct
    except Exception:
        return {}


def build_executor() -> "AgentExecutor":
    """agent_executor_builder for the A2aAgent template (called once at set_up)."""
    return SalesA2aExecutor()


# --- Agent card (skill the CES Sales Master routes to) --------------------------
# Description mirrors the old OpenAPI operation summary so the routing model treats
# it the same. The interface URL is filled in by the template at set_up.
_SKILL = AgentSkill(
    id="call_sales_specialist",
    name="AT&T Sales Specialist",
    description=(
        "Reach the AT&T sales specialist for ANY device upgrade, phone, plan, line, "
        "trade-in, price, or order request. The specialist owns the phone catalog, "
        "pricing, eligibility, trade-in values, and order placement."
    ),
    tags=["sales", "device", "upgrade", "plan", "trade-in", "order"],
    examples=["I want to upgrade my phone", "what plans do you have", "trade in my old phone"],
)

_AGENT_CARD = create_agent_card(
    agent_name="AT&T Telephony Sales Specialist",
    description="Voice-tuned AT&T phone-upgrade sales agent, reachable over A2A for the IVR path.",
    skills=[_SKILL],
)

# Module-level instance is what gets deployed (agent=a2a_agent).
a2a_agent = A2aAgent(agent_card=_AGENT_CARD, agent_executor_builder=build_executor)
