from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger("audiocodes")  # shares the handler configured in server.py

from relay.channels import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd, AgentTurnComplete,
    CallerAudio, CallerEnd,
)
from relay.call_session import SessionRecord


# --------------------------------------------------------------------------- #
# Routing: greeter-emitted intent -> specialist                               #
# --------------------------------------------------------------------------- #
GREETER_KEY = "greeter"
DEFAULT_KEY = "internet"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    backend: str   # "adk" | "ces"
    display: str


ROUTES: dict[str, AgentSpec] = {
    "internet": AgentSpec("internet", "adk", "Internet support"),
    "phone_upgrade": AgentSpec("phone_upgrade", "adk", "Phone upgrade"),
    "billing": AgentSpec("billing", "ces", "Billing"),
}


GREETER_DISPLAY = "Greeter"


def route(intent: str) -> AgentSpec:
    """Map a greeter-emitted intent string to a specialist. Unknown -> default."""
    key = (intent or "").strip().lower()
    return ROUTES.get(key, ROUTES[DEFAULT_KEY])


def display_for(key: str) -> str:
    """Human label for an agent key (greeter + specialists) — drives the UI badge."""
    if key == GREETER_KEY:
        return GREETER_DISPLAY
    spec = ROUTES.get(key)
    return spec.display if spec else key


async def _emit_agent_state(gateway, key: str) -> None:
    """Send the agent-indicator frame if the gateway supports it (UI-only)."""
    fn = getattr(gateway, "agent_state", None)
    if fn is not None:
        try:
            await fn(key, display_for(key))
        except Exception:
            pass


async def _emit_turn_complete(gateway) -> None:
    """Tell the gateway the agent finished its turn, so it releases the media floor
    (AudioCodes playStream.stop). Best-effort: gateways without end_turn skip it."""
    fn = getattr(gateway, "end_turn", None)
    if fn is not None:
        try:
            await fn()
        except Exception:
            pass


async def _emit_transcript(gateway, ev: AgentTranscript) -> None:
    """Send a live-transcript frame if the gateway supports it (UI-only)."""
    fn = getattr(gateway, "transcript", None)
    if fn is not None:
        try:
            await fn(ev.role, ev.text, ev.final)
        except Exception:
            pass


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
            # Tell the UI which agent is live now (greeter, then specialist).
            await _emit_agent_state(gateway, key)
            swap = None
            async for ev in agent.events():
                if isinstance(ev, AgentAudio):
                    await gateway.send_audio(ev.pcm)
                elif isinstance(ev, AgentTranscript):
                    await _emit_transcript(gateway, ev)
                    if ev.final:
                        log.info("[steer] %s/%s transcript final: %r",
                                 key, ev.role, (ev.text or "")[:160])
                        record.add_turn(ev.role, ev.text)
                elif isinstance(ev, AgentTurnComplete):
                    log.info("[steer] %s turn complete -> release floor", key)
                    await _emit_turn_complete(gateway)
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
    # Close the active backend channel on ANY teardown path. A caller hangup
    # cancels agent_to_caller mid-stream, before its own agent.close() runs, so
    # without this the AE/CES/Live connection would leak on every caller-ended call.
    agent = state.get("agent")
    if agent is not None:
        try:
            await agent.close()
        except Exception:
            pass
    await gateway.end()
