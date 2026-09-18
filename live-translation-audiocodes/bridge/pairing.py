"""Pairs the caller leg with the agent leg.

Both legs dial in to the same number: the first inbound call waits, and the next
one to arrive becomes its agent leg. In-memory: one bridge process owns both legs
of a call (POC scope).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class CallPair:
    caller_conversation_id: str
    agent_gateway: object | None = None
    agent_events: object | None = None
    agent_joined: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class CallRegistry:
    def __init__(self):
        self._pairs: dict[str, CallPair] = {}

    def create(self, caller_conversation_id: str) -> CallPair:
        pair = CallPair(caller_conversation_id)
        self._pairs[caller_conversation_id] = pair
        return pair

    def join(self, caller_conversation_id: str, gateway, events) -> CallPair | None:
        pair = self._pairs.get(caller_conversation_id)
        if pair is None or pair.agent_gateway is not None:
            return None
        pair.agent_gateway = gateway
        pair.agent_events = events
        pair.agent_joined.set()
        return pair

    def waiting_caller(self) -> str | None:
        """Oldest caller still waiting for an agent (dial-in pairing)."""
        return next((cid for cid, p in self._pairs.items() if p.agent_gateway is None), None)

    def remove(self, caller_conversation_id: str) -> None:
        self._pairs.pop(caller_conversation_id, None)
