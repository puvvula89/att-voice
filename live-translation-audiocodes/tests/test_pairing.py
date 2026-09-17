import asyncio

from bridge.pairing import CallRegistry


def test_dialin_pairs_next_call_with_oldest_waiting_caller():
    async def run():
        reg = CallRegistry()
        assert reg.waiting_caller() is None
        p1 = reg.create("caller-1")
        reg.create("caller-2")
        assert reg.waiting_caller() == "caller-1"

        joined = reg.join("caller-1", gateway="agent-gw", events="agent-events")
        assert joined is p1 and p1.agent_joined.is_set()
        assert reg.waiting_caller() == "caller-2"
        assert reg.join("caller-1", gateway="other", events=None) is None  # already paired

        reg.remove("caller-2")
        assert reg.waiting_caller() is None

    asyncio.run(run())


def test_failed_dialout_releases_waiting_caller():
    async def run():
        reg = CallRegistry()
        pair = reg.create("caller-1")
        pair.agent_conversation_id = "agent-conv"
        reg.fail_dialout("unrelated")
        assert not pair.dialout_failed.is_set()
        reg.fail_dialout("agent-conv")
        assert pair.dialout_failed.is_set()

    asyncio.run(run())
