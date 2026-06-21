"""Observe bridge: broadcast one live call's frames to read-only monitors.

The caller side (a `BrowserGateway`, later an `AudioCodesGateway`) publishes every
outgoing frame it sends to its caller (audio / transcript / agent / transfer) onto
the bus; observer WebSockets (the `/audiocodes` monitor page) subscribe and receive
those frames without sending anything back.

Demo scope: a SINGLE active call. A new caller becomes the active call; observers
always watch the active one. (Call-id rooms can replace this later without touching
the gateway or UI — same frame contract.)
"""
from __future__ import annotations

import asyncio


class CallBus:
    def __init__(self) -> None:
        self._observers: set[asyncio.Queue] = set()
        self._active = False
        self._last_agent: dict | None = None  # replayed to late-joining observers

    # --- caller side ---------------------------------------------------------
    def start(self) -> None:
        """A caller call began — tell observers to go live and reset their view."""
        self._active = True
        self._last_agent = None
        self._broadcast({"type": "call_active"})

    def end(self) -> None:
        """The caller call ended — tell observers to return to the waiting state."""
        self._active = False
        self._last_agent = None
        self._broadcast({"type": "call_end"})

    def publish(self, frame: dict) -> None:
        """Fan a caller-bound frame out to all observers (best-effort)."""
        if frame.get("type") == "agent":
            self._last_agent = frame  # so a late joiner sees the current specialist
        self._broadcast(frame)

    # --- observer side -------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        """Register an observer; seed it with the current call state."""
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        q.put_nowait({"type": "call_active"} if self._active else {"type": "call_idle"})
        if self._active and self._last_agent:
            q.put_nowait(self._last_agent)
        self._observers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._observers.discard(q)

    # --- internals -----------------------------------------------------------
    def _broadcast(self, frame: dict) -> None:
        for q in list(self._observers):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                pass  # slow observer: drop (audio frames are disposable)
