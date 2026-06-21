"""The relay's session model: the canonical per-call record + session resolution.

`SessionRecord` is the relay-owned record of one call (the session-of-record).
`resolve_session` picks which ADK session a connection lands on (identity-anchored
resume), so a flow started by the greeter is continued by the specialist on the
same session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple


# --------------------------------------------------------------------------- #
# Session-of-record                                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Turn:
    role: str   # "user" | "agent"
    text: str


@dataclass
class SessionRecord:
    """Relay-owned canonical record of one call, keyed by session_id.

    The session-of-record stitches continuity across platforms: ADK specialists
    inherit it via a shared session service; the CES specialist is seeded from
    context_summary() through historical context.
    """

    session_id: str
    caller: str = ""
    intent: str | None = None
    turns: list[Turn] = field(default_factory=list)

    def add_turn(self, role: str, text: str) -> None:
        if text:
            self.turns.append(Turn(role, text))

    def set_intent(self, intent: str) -> None:
        self.intent = intent

    def transcript_text(self) -> str:
        return "\n".join(f"{t.role}: {t.text}" for t in self.turns)

    def context_summary(self) -> str:
        intent = self.intent or "unknown"
        return (
            f"Caller intent: {intent}.\n"
            f"Prior conversation so far:\n{self.transcript_text()}"
        )


# --------------------------------------------------------------------------- #
# Session resolution (identity-anchored resume)                               #
# --------------------------------------------------------------------------- #
# A channel connects with a ``user_id`` and, optionally, a specific
# ``session_id``. To carry continuity (greeter -> specialist) we resume the
# user's existing session rather than always starting fresh. The anchor is the
# ``user_id``; the ``session_id`` is looked up here.
#
# Resolution order:
#   1. explicit ``session_id`` (same-tab reconnect) -> ``get_session``
#   2. else the user's most-recently-updated session -> ``list_sessions`` -> ``get_session``
#   3. else ``create_session`` (brand-new identity / fresh demo run)
#
# Works with any ADK ``BaseSessionService``: ``InMemorySessionService`` locally,
# ``VertexAiSessionService`` (the shared store) for the deployed path.


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
