"""Flatten an ADK event stream into a single speakable string for the voice path.

``async_stream_query`` yields a stream of events aimed at driving the browser UI:
a ``session_info`` control message, agent text (model content parts), ``pending_ui``
state deltas, partial events, and transcripts. The CXAS voice path needs none of
that structure — just the agent's final spoken words. This collapses the stream
to that text and drops everything else (UI components, partials, non-model roles).
"""
from typing import Iterable


def flatten_events(events: Iterable[dict]) -> str:
    """Return the concatenated final model text from an ADK event stream.

    Keeps only complete (non-``partial``) events whose ``content.role`` is
    ``"model"``, joining their text parts. Multiple final model events are joined
    with a single space. Everything else (``pending_ui``, control messages,
    partials, non-model roles, text-less parts) is ignored. Empty when no text.
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
