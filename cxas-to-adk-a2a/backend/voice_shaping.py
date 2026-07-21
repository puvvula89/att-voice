"""Pure voice-shaping helpers for the A2A IVR path (no ADK / a2a imports).

These are the jobs the old HTTP adapter did, now that CES calls the ADK agent
directly over A2A: pull the caller's inputs out of the inbound A2A message, mark
the turn as IVR + attach the caller's sentiment for the text-only agent, and
collapse the agent's event stream to one speakable line. Kept dependency-free so
they unit-test without a2a-sdk or a live Agent Engine.
"""
from typing import Any, Dict, Iterable, Optional

# Spoken when a turn produced no agent text (e.g. a fresh session where the agent
# emitted only a tool/UI-staging event). The IVR path is voice-only — an empty
# reply is dead air, so we always return something speakable.
EMPTY_TURN_FALLBACK = "One moment, please."

# The chat agent reads this marker to switch into voice/IVR mode: no browser UI
# staging (render_component), brief spoken replies. A before_model_callback on the
# agent (hide_ui_for_ivr) also strips render_component when present.
CHANNEL_MARKER = "[channel: ivr]"


def flatten_events(events: Iterable[dict]) -> str:
    """Return the concatenated final model text from an ADK event stream.

    Keeps only complete (non-``partial``) events whose ``content.role`` is
    ``"model"``, joining their text parts. Everything else (``pending_ui``,
    control messages, partials, non-model roles, text-less parts) is ignored.
    Empty when no text.
    """
    texts = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("partial"):
            continue
        content = ev.get("content") or {}
        if content.get("role") != "model":
            continue
        parts = content.get("parts") or []
        text = "".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")
        )
        if text.strip():
            texts.append(text.strip())
    return " ".join(texts)


def speakable_reply(events: Iterable[dict]) -> str:
    """Flatten the event stream to one line, substituting the fallback when empty."""
    text = flatten_events(events)
    return text if text.strip() else EMPTY_TURN_FALLBACK


def sentiment_envelope(sentiment: Optional[Dict[str, Any]]) -> str:
    """Render a compact sentiment note for the ADK message, or "" if none.

    Text-only agents can't hear tone, so we surface the caller's current-turn
    sentiment inline for the model to read and adjust tone / escalation.
    """
    if not sentiment:
        return ""
    label = sentiment.get("label", "unknown")
    score = sentiment.get("score")
    score_s = f"; score={score:.2f}" if isinstance(score, (int, float)) else ""
    return f"[caller_sentiment: label={label}{score_s}]"


def augment_message(utterance: str, sentiment: Optional[Dict[str, Any]]) -> str:
    """Build the ADK message: caller utterance + optional sentiment + IVR marker."""
    parts = [utterance or ""]
    env = sentiment_envelope(sentiment)
    if env:
        parts.append(env)
    parts.append(CHANNEL_MARKER)
    return "\n\n".join(parts)


def extract_tool_inputs(
    text: Optional[str], metadata: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Pull the caller inputs out of an inbound A2A message.

    CES variable-mapping delivers the structured fields (``customer_id``,
    ``session_id``, sentiment) in the message ``metadata``; the caller's words
    arrive as the message text. Sentiment is assembled from the model-supplied
    label/score (absent label -> no sentiment envelope). Everything is defensive:
    a missing metadata dict just yields the utterance with no ids.
    """
    meta = metadata or {}
    label = meta.get("caller_sentiment_label")
    sentiment = (
        {"label": label, "score": meta.get("caller_sentiment_score")} if label else None
    )
    return {
        "customer_id": meta.get("customer_id"),
        "session_id": meta.get("session_id"),
        "utterance": (text or "").strip(),
        "sentiment": sentiment,
        "correlation_id": meta.get("correlation_id"),
        "turn": meta.get("turn"),
    }
