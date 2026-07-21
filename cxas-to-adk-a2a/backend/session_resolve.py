"""Resolve which session a connecting user lands on (identity-anchored resume).

A channel (voice or chat) connects with a ``user_id`` and, optionally, a specific
``session_id``. To support cross-channel handoff — start in chat, continue in
voice (or vice versa) — we resume the user's existing session rather than always
starting fresh. The anchor is the ``user_id``; the ``session_id`` is looked up
here, not carried by the human between channels.

Resolution order:
  1. explicit ``session_id`` (same-tab reconnect) -> ``get_session``
  2. else the user's most-recently-updated session -> ``list_sessions`` -> ``get_session``
  3. else ``create_session`` (brand-new identity / fresh demo run)

A resume-window (TTL) guards steps 1-2: a candidate session is only resumed if its
last activity was within ``ttl_seconds`` (default 600s / 10 min, override via
``SESSION_RESUME_TTL_SECONDS``). Past the window a returning user gets a FRESH
session — the stale one is left in the store, never deleted. This is a resume
policy, not a teardown: ending a call closes the live channel; the record stays.

Works with any ADK ``BaseSessionService``: ``InMemorySessionService`` for local
Topology A, ``VertexAiSessionService`` (the shared store) for the deployed path.
Both chat and voice point their service at the same ``agent_engine_id``, so step 2
sees sessions created by the other channel.
"""
import os
import time
from typing import Any, Tuple

_DEFAULT_TTL_SECONDS = 600.0  # 10-minute resume window for a returning user


def _resume_ttl(ttl_seconds: float | None) -> float:
    """Resolve the resume window: explicit arg > env > default."""
    if ttl_seconds is not None:
        return ttl_seconds
    raw = os.environ.get("SESSION_RESUME_TTL_SECONDS")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_TTL_SECONDS


def _session_epoch(session) -> float:
    """Best-effort epoch seconds for a session's last update (0 if unknown).

    ``InMemorySessionService`` uses a float; ``VertexAiSessionService`` may hand
    back a datetime — normalise both.
    """
    t = getattr(session, "last_update_time", 0) or 0
    if hasattr(t, "timestamp"):  # datetime
        try:
            return t.timestamp()
        except Exception:
            return 0.0
    try:
        return float(t)
    except (TypeError, ValueError):
        return 0.0


async def resolve_session(
    session_service,
    app_name: str,
    user_id: str,
    session_id: str | None = None,
    *,
    ttl_seconds: float | None = None,
    now: float | None = None,
) -> Tuple[Any, bool]:
    """Return ``(session, resumed)`` for this connection.

    ``resumed`` is True when an existing session was found (by id or by user_id)
    AND it is within the resume window; False when a fresh one was created (no
    prior session, or the latest one is older than ``ttl_seconds``).
    """
    ttl = _resume_ttl(ttl_seconds)
    now = time.time() if now is None else now

    candidate = None
    if session_id:
        candidate = await _safe_get(session_service, app_name, user_id, session_id)

    if candidate is None:
        latest_id = await _latest_session_id(session_service, app_name, user_id)
        if latest_id:
            candidate = await _safe_get(session_service, app_name, user_id, latest_id)

    # Resume only if the candidate is still warm (within the TTL window).
    if candidate is not None and (now - _session_epoch(candidate)) <= ttl:
        return candidate, True

    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    return session, False


async def _safe_get(session_service, app_name, user_id, session_id):
    """get_session that yields None on miss whether the service returns or raises."""
    try:
        return await session_service.get_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
    except Exception:
        return None


async def _latest_session_id(session_service, app_name, user_id):
    """Id of the user's most-recently-updated session, or None if they have none.

    ``list_sessions`` returns shallow sessions (often no state/events), so callers
    re-fetch the chosen id via ``get_session`` to get full state.
    """
    try:
        listed = await session_service.list_sessions(app_name=app_name, user_id=user_id)
    except Exception:
        return None
    sessions = getattr(listed, "sessions", listed) or []
    if not sessions:
        return None
    latest = max(sessions, key=lambda s: getattr(s, "last_update_time", 0) or 0)
    return getattr(latest, "id", None)
