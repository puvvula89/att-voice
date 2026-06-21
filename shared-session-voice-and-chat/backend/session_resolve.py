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

Works with any ADK ``BaseSessionService``: ``InMemorySessionService`` for local
Topology A, ``VertexAiSessionService`` (the shared store) for the deployed path.
Both chat and voice point their service at the same ``agent_engine_id``, so step 2
sees sessions created by the other channel.
"""
from typing import Any, Tuple


async def resolve_session(
    session_service,
    app_name: str,
    user_id: str,
    session_id: str | None = None,
) -> Tuple[Any, bool]:
    """Return ``(session, resumed)`` for this connection.

    ``resumed`` is True when an existing session was found (by id or by user_id),
    False when a fresh one was created.
    """
    session = None

    if session_id:
        session = await _safe_get(session_service, app_name, user_id, session_id)

    if session is None:
        latest_id = await _latest_session_id(session_service, app_name, user_id)
        if latest_id:
            session = await _safe_get(session_service, app_name, user_id, latest_id)

    resumed = session is not None
    if session is None:
        session = await session_service.create_session(app_name=app_name, user_id=user_id)
    return session, resumed


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
