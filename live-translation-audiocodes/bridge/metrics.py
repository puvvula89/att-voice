"""Per-utterance latency and per-call recording (PRD §11).

Speech onset is detected by energy on the audio the bridge receives; an utterance
ends after `silence_ms` of quiet. Translated output lags the speech, so output is
grouped into bursts (a burst starts after `burst_gap_ms` without output) and each
burst start is attributed to the earliest utterance still waiting for output.

Per utterance, relative to its speech onset:
  ttfa_ms        first translated audio chunk received from Gemini
  ttft_ms        first output transcription text received from Gemini
  first_send_ms  first translated chunk forwarded to the telephony side
Events are logged as JSON lines keyed by conversation ID; a summary is logged when
the call ends. Source and translated audio are written to recordings/<conv>/.
"""
from __future__ import annotations

import array
import json
import logging
import math
import os
import statistics
import time
import wave

log = logging.getLogger("bridge.metrics")

IN_RATE = 16000
OUT_RATE = 24000
_KEYS = ("ttfa_ms", "ttft_ms", "first_send_ms")


def rms(pcm: bytes) -> float:
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class CallMetrics:
    def __init__(self, conversation_id: str, direction: str, *,
                 threshold: float = 500.0, silence_ms: int = 700, burst_gap_ms: int = 400,
                 record_dir: str | None = "recordings", clock=time.monotonic):
        self.conv = conversation_id or "unknown"
        self.direction = direction
        self._threshold = threshold
        self._silence_s = silence_ms / 1000
        self._gap_s = burst_gap_ms / 1000
        self._clock = clock
        self._utterances: list[dict] = []
        self._speaking = False
        self._quiet_s = 0.0
        self._last = {"audio": None, "text": None}
        self._audio_burst: dict | None = None
        self._in_wav = self._out_wav = None
        if record_dir:
            path = os.path.join(record_dir, self.conv)
            os.makedirs(path, exist_ok=True)
            self._in_wav = self._open_wav(os.path.join(path, f"{direction}-source.wav"), IN_RATE)
            self._out_wav = self._open_wav(os.path.join(path, f"{direction}-translated.wav"), OUT_RATE)

    @staticmethod
    def _open_wav(path, rate):
        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        return w

    def _emit(self, event: str, **fields) -> None:
        log.info(json.dumps({"conv": self.conv, "direction": self.direction, "event": event, **fields},
                            ensure_ascii=False))

    # --- inbound ------------------------------------------------------------
    def on_inbound(self, pcm: bytes) -> None:
        if self._in_wav:
            self._in_wav.writeframes(pcm)
        if rms(pcm) >= self._threshold:
            self._quiet_s = 0.0
            if not self._speaking:
                self._speaking = True
                u = {"n": len(self._utterances) + 1, "onset": self._clock(), **{k: None for k in _KEYS}}
                self._utterances.append(u)
                self._emit("speech_onset", utterance=u["n"])
        elif self._speaking:
            self._quiet_s += len(pcm) / 2 / IN_RATE
            if self._quiet_s >= self._silence_s:
                self._speaking = False
                self._quiet_s = 0.0

    # --- outbound -----------------------------------------------------------
    def _burst_start(self, kind: str, now: float) -> bool:
        last = self._last[kind]
        self._last[kind] = now
        return last is None or now - last >= self._gap_s

    def _pending(self, key: str) -> dict | None:
        return next((u for u in self._utterances if u[key] is None), None)

    def _stamp(self, u: dict, key: str, now: float) -> None:
        u[key] = round((now - u["onset"]) * 1000)

    def record_model_audio(self, pcm: bytes) -> None:
        """Write every model output chunk (silence included) to the recording."""
        if self._out_wav:
            self._out_wav.writeframes(pcm)

    def on_model_audio(self, pcm: bytes) -> None:
        """A non-silent translated chunk: drives time-to-first-audio."""
        now = self._clock()
        if self._burst_start("audio", now):
            u = self._pending("ttfa_ms")
            self._audio_burst = u
            if u:
                self._stamp(u, "ttfa_ms", now)
                self._emit("first_audio", utterance=u["n"], ttfa_ms=u["ttfa_ms"])

    def on_forwarded(self) -> None:
        u = self._audio_burst
        if u and u["first_send_ms"] is None:
            self._stamp(u, "first_send_ms", self._clock())

    def on_transcript(self, kind: str, text: str, language: str) -> None:
        if kind == "output":
            now = self._clock()
            if self._burst_start("text", now):
                u = self._pending("ttft_ms")
                if u:
                    self._stamp(u, "ttft_ms", now)
        self._emit("transcript", kind=kind, text=text, language=language)

    # --- end ----------------------------------------------------------------
    def summary(self) -> dict:
        for u in self._utterances:
            self._emit("utterance", **{k: v for k, v in u.items() if k != "onset"})
        out = {"utterances": len(self._utterances)}
        for key in _KEYS:
            vals = [u[key] for u in self._utterances if u[key] is not None]
            if vals:
                out[key] = {"min": min(vals), "median": round(statistics.median(vals)), "max": max(vals),
                            "values": vals}
        self._emit("summary", **out)
        for w in (self._in_wav, self._out_wav):
            if w:
                w.close()
        return out
