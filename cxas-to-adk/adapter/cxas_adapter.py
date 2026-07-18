"""CXAS request/response adapter core.

CXAS calls a tool over plain HTTP (one text in, one text out) — it cannot hold a
WebSocket like the browser. This turns one CXAS turn into one call against the
shared chat agent's ``async_stream_query``, consuming the event stream into a
single speakable reply plus the resolved session id.

Session get-or-create (and the TTL guard) live server-side in the deployed chat
app; here we only forward ``customer_id`` (as the ADK ``user_id``) and an optional
cached ``session_id``, then read the ``session_info`` control event for the id the
server resolved.
"""
import json
import logging
import uuid
from typing import Any, Dict, Optional

from adapter.flatten import flatten_events

# Spoken when a turn produced no agent text (e.g. a fresh session where the shared
# chat agent emitted only a tool/UI-staging event). CXAS is voice-only over HTTP —
# an empty reply is dead air on the call, so we always return something speakable.
EMPTY_TURN_FALLBACK = "One moment, please."

# One structured record per CXAS turn — the join key between the CXAS conversation
# and the ADK session for later analysis (see DESIGN.md §"Observability").
_ASSOCIATION_LOG = logging.getLogger("cxas.association")


def log_association(
    *,
    customer_id: str,
    session_id: Optional[str],
    correlation_id: Optional[str] = None,
    turn: Optional[int] = None,
    channel: str = "ivr",
    error: bool = False,
    sentiment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Emit and return one association record tying a CXAS turn to an ADK session.

    ``correlation_id`` is minted when absent so every turn is traceable.
    """
    record = {
        "event": "cxas_turn",
        "correlation_id": correlation_id or uuid.uuid4().hex,
        "customer_id": customer_id,
        "session_id": session_id,
        "channel": channel,
        "turn": turn,
        "error": error,
        "sentiment": sentiment,
    }
    _ASSOCIATION_LOG.info(json.dumps(record))
    return record


def sentiment_envelope(sentiment: Optional[Dict[str, Any]]) -> str:
    """Render a compact, readable sentiment note for the ADK message, or "" if none.

    Text-only ADK agents can't hear tone, so we surface the caller's current-turn
    sentiment inline. The ADK model reads it and adjusts tone / escalation. No
    persistence: the trend lives implicitly in ADK's own conversation history.
    """
    if not sentiment:
        return ""
    label = sentiment.get("label", "unknown")
    score = sentiment.get("score")
    score_s = f"; score={score:.2f}" if isinstance(score, (int, float)) else ""
    return f"[caller_sentiment: label={label}{score_s}]"


# The chat agent (shared with the browser) reads this marker to switch into a
# voice/IVR mode: no browser UI staging (render_component), brief spoken replies.
# A before_model_callback on the ADK agent also hides render_component when it's
# present, so the model can't spend round-trips staging UI the phone path discards.
CHANNEL_MARKER = "[channel: ivr]"


def _augment(utterance: str, sentiment: Optional[Dict[str, Any]]) -> str:
    parts = [utterance]
    env = sentiment_envelope(sentiment)
    if env:
        parts.append(env)
    parts.append(CHANNEL_MARKER)
    return "\n\n".join(parts)


async def run_cxas_turn(
    agent: Any,
    *,
    customer_id: str,
    utterance: str,
    session_id: Optional[str] = None,
    sentiment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one CXAS turn against ``agent`` and return
    ``{"response_text": <text>, "session_id": <id>, "sentiment": <dict|None>}``.

    ``customer_id`` is passed as the ADK ``user_id`` (the cross-channel anchor).
    ``session_id`` is forwarded only when provided (resume-by-id path).
    ``sentiment`` — the caller's current-turn sentiment ``{"label", "score"}`` as
    assessed by the CES steering model (which already reads the utterance) and passed
    through the tool call. When present it is injected into the ADK message so the
    text-only specialist can adjust tone/escalation. No sentiment model call happens
    here anymore, so the turn incurs no extra Cloud Run -> Gemini hop.
    """
    kwargs: Dict[str, Any] = {
        "user_id": customer_id,
        "message": _augment(utterance, sentiment),
    }
    if session_id:
        kwargs["session_id"] = session_id

    resolved_session_id = session_id
    events = []
    async for ev in agent.async_stream_query(**kwargs):
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "session_info":
            if ev.get("session_id"):
                resolved_session_id = ev["session_id"]
            continue
        events.append(ev)

    response_text = flatten_events(events)
    empty = not response_text.strip()
    return {
        "response_text": EMPTY_TURN_FALLBACK if empty else response_text,
        "session_id": resolved_session_id,
        "sentiment": sentiment,
        "empty_turn": empty,
    }
