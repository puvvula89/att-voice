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
