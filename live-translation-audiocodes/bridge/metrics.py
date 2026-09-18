"""Per-utterance latency and per-call recording (PRD §11).

Speech onset is detected by energy on the audio the bridge receives; an utterance
ends after `silence_ms` of quiet. Translated output lags the speech, so output is
grouped into bursts (a burst starts after `burst_gap_ms` without output) and each
burst start is attributed to the earliest utterance still waiting for output.

Per utterance, relative to its speech onset:
  send_ms        first audio chunk containing this utterance handed to Gemini
  ttfa_ms        first translated audio chunk received from Gemini
  ttft_ms        first output transcription text received from Gemini
  first_send_ms  first translated chunk forwarded to the telephony side
`send_ms` isolates the 100 ms send buffer in `translator.py`, which would otherwise
be charged to the model. The legs before the bridge (mic -> PSTN -> VAIC) and after
it (VAIC -> PSTN -> earpiece) carry no timestamps and are not observable here.

Events are logged as JSON lines keyed by conversation ID, and appended to
recordings/<conv>/events.jsonl for the console service to tail and replay. A summary
is logged when the call ends. Source and translated audio go to recordings/<conv>/.
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
_KEYS = ("send_ms", "ttfa_ms", "ttft_ms", "first_send_ms")


def rms(pcm: bytes) -> float:
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class CallMetrics:
    def __init__(self, conversation_id: str, direction: str, *,
                 threshold: float = 500.0, silence_ms: int = 700, burst_gap_ms: int = 400,
                 max_wait_ms: int = 12000,
                 record_dir: str | None = "recordings", clock=time.monotonic):
        self.conv = conversation_id or "unknown"
        self.direction = direction
        self._threshold = threshold
        self._silence_s = silence_ms / 1000
        self._gap_s = burst_gap_ms / 1000
        self._max_wait_s = max_wait_ms / 1000
        self._clock = clock
        self._utterances: list[dict] = []
        self._speaking = False
        self._quiet_s = 0.0
        self._last = {"audio": None, "text": None}
        self._audio_burst: dict | None = None
        self._text_burst: dict | None = None
        self._in_wav = self._out_wav = self._events = None
        if record_dir:
            path = os.path.join(record_dir, self.conv)
            os.makedirs(path, exist_ok=True)
            self._in_wav = self._open_wav(os.path.join(path, f"{direction}-source.wav"), IN_RATE)
            self._out_wav = self._open_wav(os.path.join(path, f"{direction}-translated.wav"), OUT_RATE)
            # Both directions append to one file; line-buffered so the console
            # service sees each event as it happens.
            self._events = open(os.path.join(path, "events.jsonl"), "a", buffering=1,
                                encoding="utf-8")

    @staticmethod
    def _open_wav(path, rate):
        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        return w

    def _emit(self, event: str, **fields) -> None:
        # `ts` is wall clock: the console shows when each utterance was spoken and
        # when its translation went out, which monotonic time cannot express.
        line = json.dumps({"conv": self.conv, "direction": self.direction, "event": event,
                           "ts": round(time.time(), 3), **fields}, ensure_ascii=False)
        log.info(line)
        if self._events:
            try:
                self._events.write(line + "\n")
            except ValueError:  # file closed by summary() while a task was still running
                pass

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
        """The utterance an arriving burst belongs to, newest first.

        Not every utterance produces output -- a cough, a half word, or speech the
        model chose not to translate. Taking the oldest unanswered utterance would
        let one of those absorb every later burst and report a 30 second latency for
        a 2 second translation, so the newest waiting utterance wins, and a burst
        that arrives long after its onset is left unattributed rather than charged
        to something stale.
        """
        for u in reversed(self._utterances):
            if u[key] is None:
                return u if self._clock() - u["onset"] <= self._max_wait_s else None
        return None

    def _stamp(self, u: dict, key: str, now: float) -> None:
        u[key] = round((now - u["onset"]) * 1000)

    def on_model_send(self) -> None:
        """A buffered chunk left the bridge for Gemini: closes the send-buffer leg."""
        u = self._pending("send_ms")
        if u:
            self._stamp(u, "send_ms", self._clock())
            self._emit("model_send", utterance=u["n"], send_ms=u["send_ms"])

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
        # Tag each transcript with an utterance so the console can pair what was
        # said with how it came out, instead of guessing from timestamps.
        if kind == "output":
            now = self._clock()
            if self._burst_start("text", now):
                u = self._pending("ttft_ms")
                if u:
                    self._stamp(u, "ttft_ms", now)
                    self._text_burst = u
            u = self._text_burst
        else:
            u = self._utterances[-1] if self._utterances else None
        self._emit("transcript", kind=kind, text=text, language=language,
                   utterance=u["n"] if u else None)

    # --- end ----------------------------------------------------------------
    def summary(self) -> dict:
        for u in self._utterances:
            # Keyed `utterance` like every other event, so consumers can group on
            # one field. This row carries `first_send_ms`, which nothing else emits.
            self._emit("utterance", utterance=u["n"],
                       **{k: v for k, v in u.items() if k not in ("onset", "n")})
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
        if self._events:
            self._events.close()
        return out
