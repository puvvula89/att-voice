from __future__ import annotations

import asyncio

from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)
from relay.router import route, GREETER_KEY
from relay.session_record import SessionRecord


async def run_call(gateway, agent_factory, record: SessionRecord) -> None:
    """Drive one call: greeter -> intent -> seamless swap to specialist.

    agent_factory(key, record) -> AgentSession. The same record is passed to
    every agent so context carries (ADK shares the session; CES is seeded from it).
    """
    done = asyncio.Event()
    state = {"agent": None, "swap_to": None}

    async def caller_to_agent():
        async for ev in gateway.events():
            if isinstance(ev, CallerAudio):
                agent = state["agent"]
                if agent is not None:
                    await agent.send_audio(ev.pcm)
            elif isinstance(ev, CallerEnd):
                break
        done.set()

    async def agent_to_caller():
        # Loop across agents: greeter first, then whatever swap is requested.
        key = GREETER_KEY
        while True:
            agent = agent_factory(key, record)
            await agent.open(record)
            state["agent"] = agent
            swap = None
            async for ev in agent.events():
                if isinstance(ev, AgentAudio):
                    await gateway.send_audio(ev.pcm)
                elif isinstance(ev, AgentTranscript):
                    if ev.final:
                        record.add_turn(ev.role, ev.text)
                elif isinstance(ev, AgentIntent):
                    record.set_intent(ev.intent)
                    swap = route(ev.intent).key
                    break  # greeter goes silent; close below and open specialist
                elif isinstance(ev, AgentEnd):
                    swap = None
                    break
            await agent.close()
            state["agent"] = None
            if swap is None:
                break
            key = swap  # open specialist next iteration; NO re-greet handled by prompt
        done.set()

    task_in = asyncio.create_task(caller_to_agent())
    task_out = asyncio.create_task(agent_to_caller())
    await done.wait()
    for t in (task_in, task_out):
        t.cancel()
    await asyncio.gather(task_in, task_out, return_exceptions=True)
    await gateway.end()
