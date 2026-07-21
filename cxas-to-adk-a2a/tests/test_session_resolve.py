import asyncio

from google.adk.sessions import InMemorySessionService

from backend.session_resolve import resolve_session

APP = "phone_upgrade"


def _run(coro):
    return asyncio.run(coro)


def test_creates_fresh_when_user_has_no_sessions():
    async def go():
        svc = InMemorySessionService()
        session, resumed = await resolve_session(svc, APP, "alice")
        assert resumed is False
        assert session.id

    _run(go())


def test_resumes_by_user_id_without_session_id():
    """The handoff case: arrive with only a user_id, land on the user's session."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="bob")
        session, resumed = await resolve_session(svc, APP, "bob")  # no session_id
        assert resumed is True
        assert session.id == existing.id

    _run(go())


def test_resumes_explicit_session_id():
    """Same-tab reconnect: an explicit session_id still resumes that exact session."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="carol")
        session, resumed = await resolve_session(svc, APP, "carol", session_id=existing.id)
        assert resumed is True
        assert session.id == existing.id

    _run(go())


def test_stale_session_id_falls_back_to_user_id_resume():
    """A bogus/expired session_id must not create a new session if the user has one."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="dave")
        session, resumed = await resolve_session(svc, APP, "dave", session_id="does-not-exist")
        assert resumed is True
        assert session.id == existing.id

    _run(go())


def test_picks_most_recent_session():
    async def go():
        svc = InMemorySessionService()
        await svc.create_session(app_name=APP, user_id="erin")
        await asyncio.sleep(0.02)
        second = await svc.create_session(app_name=APP, user_id="erin")
        session, resumed = await resolve_session(svc, APP, "erin")
        assert resumed is True
        assert session.id == second.id

    _run(go())


def test_different_users_are_isolated():
    async def go():
        svc = InMemorySessionService()
        await svc.create_session(app_name=APP, user_id="frank")
        session, resumed = await resolve_session(svc, APP, "grace")
        assert resumed is False

    _run(go())


def _ts(session):
    return getattr(session, "last_update_time", 0) or 0


def test_within_ttl_resumes():
    """A returning user inside the resume window lands on their existing session."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="ivan")
        session, resumed = await resolve_session(
            svc, APP, "ivan", ttl_seconds=600, now=_ts(existing) + 60
        )
        assert resumed is True
        assert session.id == existing.id

    _run(go())


def test_beyond_ttl_starts_fresh_without_deleting():
    """Past the window, a returning user gets a fresh session; the old one is kept
    (create-fresh, never delete)."""
    async def go():
        svc = InMemorySessionService()
        old = await svc.create_session(app_name=APP, user_id="heidi")
        session, resumed = await resolve_session(
            svc, APP, "heidi", ttl_seconds=600, now=_ts(old) + 700
        )
        assert resumed is False
        assert session.id != old.id
        # old session still present in the store (not deleted)
        listed = await svc.list_sessions(app_name=APP, user_id="heidi")
        ids = {s.id for s in getattr(listed, "sessions", listed)}
        assert old.id in ids

    _run(go())


def test_stale_explicit_session_id_beyond_ttl_starts_fresh():
    """Even an explicit session_id is not resumed once it is older than the window."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="judy")
        session, resumed = await resolve_session(
            svc, APP, "judy", session_id=existing.id,
            ttl_seconds=600, now=_ts(existing) + 700,
        )
        assert resumed is False
        assert session.id != existing.id

    _run(go())


def test_ttl_from_env(monkeypatch):
    """TTL falls back to SESSION_RESUME_TTL_SECONDS when not passed explicitly."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(app_name=APP, user_id="kim")
        monkeypatch.setenv("SESSION_RESUME_TTL_SECONDS", "60")
        # 120s later with a 60s env window -> stale -> fresh
        session, resumed = await resolve_session(
            svc, APP, "kim", now=_ts(existing) + 120
        )
        assert resumed is False

    _run(go())


def test_ended_session_not_resumed_starts_fresh():
    """A gracefully ended call (end_call set call_ended) must not be rejoined by a
    new call within the TTL — the new caller gets a fresh session. The ended session
    is kept (not deleted)."""
    async def go():
        svc = InMemorySessionService()
        ended = await svc.create_session(
            app_name=APP, user_id="mia", state={"call_ended": True}
        )
        session, resumed = await resolve_session(
            svc, APP, "mia", ttl_seconds=600, now=_ts(ended) + 60
        )
        assert resumed is False
        assert session.id != ended.id
        listed = await svc.list_sessions(app_name=APP, user_id="mia")
        ids = {s.id for s in getattr(listed, "sessions", listed)}
        assert ended.id in ids  # ended session preserved, just not resumed

    _run(go())


def test_incomplete_session_still_resumes():
    """A dropped/incomplete session (no call_ended) still resumes within the window."""
    async def go():
        svc = InMemorySessionService()
        existing = await svc.create_session(
            app_name=APP, user_id="noah", state={"data:line_selector": {"lines": []}}
        )
        session, resumed = await resolve_session(
            svc, APP, "noah", ttl_seconds=600, now=_ts(existing) + 60
        )
        assert resumed is True
        assert session.id == existing.id

    _run(go())
