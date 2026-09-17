"""M0 translator: plays the caller's own audio back once they pause.

VoiceAI Connect streams audio continuously, silence included, so an utterance
ends when the signal stays below an energy threshold for `silence_ms`. The
buffered speech is upsampled to 24 kHz and emitted as one utterance. Proves the
telephony path end to end before any model is involved.
"""
from __future__ import annotations

import array
import asyncio
import math

from bridge.audio_transcode import MODEL_IN_RATE, MODEL_OUT_RATE, resample_pcm16
from bridge.channels import TranslatedAudio, TurnComplete

_FRAME = int(MODEL_OUT_RATE * 0.02) * 2   # 20 ms of 24 kHz PCM16


def _rms(pcm: bytes) -> float:
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EchoTranslator:
    def __init__(self, silence_ms: int = 700, threshold: float = 500.0):
        self._silence_s = silence_ms / 1000
        self._threshold = threshold
        self._buf = bytearray()
        self._quiet_s = 0.0
        self._speaking = False
        self._out: asyncio.Queue = asyncio.Queue()

    async def open(self) -> None:
        pass

    async def send_audio(self, pcm: bytes) -> None:
        loud = _rms(pcm) >= self._threshold
        if loud:
            self._speaking = True
            self._quiet_s = 0.0
        if not self._speaking:
            return
        self._buf.extend(pcm)
        if not loud:
            self._quiet_s += len(pcm) / 2 / MODEL_IN_RATE
            if self._quiet_s >= self._silence_s:
                self._flush()

    def _flush(self) -> None:
        pcm = resample_pcm16(bytes(self._buf), MODEL_IN_RATE, MODEL_OUT_RATE)
        self._buf.clear()
        self._speaking = False
        self._quiet_s = 0.0
        for off in range(0, len(pcm), _FRAME):
            self._out.put_nowait(TranslatedAudio(pcm[off:off + _FRAME]))
        self._out.put_nowait(TurnComplete())

    async def events(self):
        while True:
            ev = await self._out.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        self._out.put_nowait(None)
