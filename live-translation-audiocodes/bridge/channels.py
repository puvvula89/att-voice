"""Events and ports shared by the transport adapter and the translators.

The call loop only depends on these types, so the playback transport (VoiceAI
Connect today, FreeSWITCH later if needed) and the translator (echo, Gemini
Live Translate) can each be swapped without touching the other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


# --- inbound from the telephony side ---------------------------------------
@dataclass
class InboundAudio:
    pcm: bytes              # PCM16 LE, 16 kHz
    participant: str = ""   # "caller" | "callee" when agent-assist mode tags it


@dataclass
class CallStart:
    """VAIC `start` activity: the call is connected."""
    parameters: dict = field(default_factory=dict)


@dataclass
class InboundEnd:
    pass


# --- outbound from a translator ---------------------------------------------
@dataclass
class TranslatedAudio:
    pcm: bytes              # PCM16 LE, 24 kHz


@dataclass
class Transcript:
    kind: str               # "input" | "output"
    text: str
    language: str = ""


@dataclass
class TurnComplete:
    """The translator finished an utterance. The gateway closes the current
    playStream (`playStream.stop`); VAIC withholds caller audio while one is open."""


@runtime_checkable
class MediaGateway(Protocol):
    """Playback-target abstraction (PRD §8)."""

    def events(self) -> AsyncIterator: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def end_turn(self) -> None: ...
    async def end(self) -> None: ...


@runtime_checkable
class Translator(Protocol):
    """One translation direction."""

    async def open(self) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    def events(self) -> AsyncIterator: ...
    async def close(self) -> None: ...
