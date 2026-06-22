from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


# --- agent-side events (channel #2: relay <- agent) ---
@dataclass
class AgentAudio:
    pcm: bytes              # PCM16 LE, 24 kHz


@dataclass
class AgentTranscript:
    role: str               # "user" | "agent"
    text: str
    final: bool


@dataclass
class AgentIntent:
    intent: str             # e.g. "internet" | "phone_upgrade" | "billing"


@dataclass
class AgentTurnComplete:
    """The agent finished speaking its turn (run_live turn_complete). Signals the
    gateway to release the media floor so the caller's audio is forwarded again —
    on AudioCodes, this is `playStream.stop`. Without it VAIC treats the bot as
    still talking and never sends the caller's `userStream`."""
    pass


@dataclass
class AgentEnd:
    pass


# --- caller-side events (WS #1: relay <- caller) ---
@dataclass
class CallerAudio:
    pcm: bytes              # PCM16 LE, 16 kHz (Phase 1 harness)


@dataclass
class CallerEnd:
    pass


@runtime_checkable
class MediaGateway(Protocol):
    """Caller-side media channel. Phase 1: harness; Phase 2: AudioCodes."""

    def events(self) -> AsyncIterator: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def transfer(self, uri: str) -> None: ...
    async def end(self) -> None: ...
    # Release the media floor at end of an agent turn (telephony only; called via
    # getattr, so gateways without it — e.g. the browser harness — skip it).
    async def end_turn(self) -> None: ...
    # UI-only frames (best-effort; relay calls these via getattr so a gateway
    # without them — e.g. a future telephony gateway — simply skips them).
    async def transcript(self, role: str, text: str, final: bool) -> None: ...
    async def agent_state(self, key: str, display: str) -> None: ...


@runtime_checkable
class AgentSession(Protocol):
    """One backend voice channel (ADK Live or CES bidi)."""

    async def open(self, record) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    def events(self) -> AsyncIterator: ...
    async def close(self) -> None: ...
