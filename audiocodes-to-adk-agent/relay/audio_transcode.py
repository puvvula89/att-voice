"""Pure audio transcoding between VoiceAI Connect coders and the ADK agent rates.

VoiceAI Connect negotiates a media format from `supportedMediaFormats` (mu-law or
linear PCM16 at 8 / 16 / 24 kHz). The ADK agents speak **16 kHz PCM16 in** and
**24 kHz PCM16 out**. This module bridges the two with hand-rolled mu-law (G.711)
and linear-interpolation resampling — Python 3.13+ removed stdlib `audioop`, so
there's nothing to lean on. Everything here is pure and unit-tested.
"""
from __future__ import annotations

import array
from dataclasses import dataclass

AGENT_IN_RATE = 16000   # what the Live agents accept (audio/pcm;rate=16000)
AGENT_OUT_RATE = 24000  # what native-audio Live emits


# --------------------------------------------------------------------------- #
# Media formats                                                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MediaFormat:
    name: str        # the VAIC token, e.g. "raw/lpcm16"
    encoding: str    # "lpcm16" | "mulaw"
    rate: int        # 8000 | 16000 | 24000
    wav: bool        # carries a WAV (RIFF) header


# Every coder VoiceAI Connect advertises in session.initiate.
_FORMATS: dict[str, MediaFormat] = {
    "raw/mulaw": MediaFormat("raw/mulaw", "mulaw", 8000, False),
    "wav/mulaw": MediaFormat("wav/mulaw", "mulaw", 8000, True),
    "raw/lpcm16": MediaFormat("raw/lpcm16", "lpcm16", 16000, False),
    "wav/lpcm16": MediaFormat("wav/lpcm16", "lpcm16", 16000, True),
    "raw/lpcm16_8": MediaFormat("raw/lpcm16_8", "lpcm16", 8000, False),
    "wav/lpcm16_8": MediaFormat("wav/lpcm16_8", "lpcm16", 8000, True),
    "raw/lpcm16_24": MediaFormat("raw/lpcm16_24", "lpcm16", 24000, False),
    "wav/lpcm16_24": MediaFormat("wav/lpcm16_24", "lpcm16", 24000, True),
}

_DEFAULT = _FORMATS["raw/lpcm16"]

# Caller-in preference: hit the agent's 16 kHz input with no resampling if we can;
# then 8 kHz linear, then mu-law, and 24 kHz last (needless downsample for input).
_USER_PREF = [
    "raw/lpcm16", "wav/lpcm16",
    "raw/lpcm16_8", "wav/lpcm16_8",
    "raw/mulaw", "wav/mulaw",
    "raw/lpcm16_24", "wav/lpcm16_24",
]
# Play-out preference: ship the agent's native 24 kHz untouched if offered;
# then 16 kHz, then 8 kHz linear, then mu-law.
_PLAY_PREF = [
    "raw/lpcm16_24", "wav/lpcm16_24",
    "raw/lpcm16", "wav/lpcm16",
    "raw/lpcm16_8", "wav/lpcm16_8",
    "raw/mulaw", "wav/mulaw",
]


def parse_format(name: str) -> MediaFormat | None:
    return _FORMATS.get(name or "")


def _pick(supported: list[str], preference: list[str]) -> MediaFormat:
    offered = {s for s in supported if s in _FORMATS}
    for name in preference:
        if name in offered:
            return _FORMATS[name]
    return _DEFAULT


def select_formats(supported: list[str]) -> tuple[MediaFormat, MediaFormat]:
    """Choose (caller-in, play-out) formats from VAIC's advertised coders.

    Returns the chosen `session.accepted` (user-stream) format and the
    `playStream.start` format, each the closest match to the agent's native
    rates so transcoding work is minimised. Unknown tokens are ignored; an empty
    list falls back to 16 kHz linear PCM.
    """
    return _pick(supported, _USER_PREF), _pick(supported, _PLAY_PREF)


# --------------------------------------------------------------------------- #
# Resampling (linear interpolation)                                           #
# --------------------------------------------------------------------------- #
def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample mono PCM16 (little-endian) between sample rates."""
    if src_rate == dst_rate or not pcm:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm)
    n = len(samples)
    if n == 0:
        return pcm
    out_n = max(1, round(n * dst_rate / src_rate))
    out = array.array("h", bytes(2 * out_n))
    ratio = (n - 1) / (out_n - 1) if out_n > 1 else 0.0
    for i in range(out_n):
        pos = i * ratio
        i0 = int(pos)
        frac = pos - i0
        s0 = samples[i0]
        s1 = samples[i0 + 1] if i0 + 1 < n else s0
        out[i] = int(s0 + (s1 - s0) * frac)
    return out.tobytes()


# --------------------------------------------------------------------------- #
# mu-law (G.711) — 16-bit PCM <-> 8-bit mu-law                                #
# --------------------------------------------------------------------------- #
_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635


def _lin2ulaw(sample: int) -> int:
    if sample < 0:
        sample = -sample
        sign = 0x80
    else:
        sign = 0x00
    if sample > _MULAW_CLIP:
        sample = _MULAW_CLIP
    sample += _MULAW_BIAS
    exponent = 7
    exp_mask = 0x4000
    while (sample & exp_mask) == 0 and exponent > 0:
        exponent -= 1
        exp_mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _ulaw2lin(byte: int) -> int:
    byte = ~byte & 0xFF
    sign = byte & 0x80
    exponent = (byte >> 4) & 0x07
    mantissa = byte & 0x0F
    magnitude = (((mantissa << 3) + _MULAW_BIAS) << exponent) - _MULAW_BIAS
    return -magnitude if sign else magnitude


def mulaw_encode(pcm: bytes) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm)
    return bytes(_lin2ulaw(s) for s in samples)


def mulaw_decode(mulaw: bytes) -> bytes:
    out = array.array("h", bytes(2 * len(mulaw)))
    for i, b in enumerate(mulaw):
        out[i] = _ulaw2lin(b)
    return out.tobytes()


# --------------------------------------------------------------------------- #
# WAV (RIFF) header — strip on decode, prepend on encode                      #
# --------------------------------------------------------------------------- #
def _wav_header(data_len: int, fmt: MediaFormat) -> bytes:
    audio_format = 7 if fmt.encoding == "mulaw" else 1  # 7 = G.711 mu-law, 1 = PCM
    bits = 8 if fmt.encoding == "mulaw" else 16
    channels = 1
    byte_rate = fmt.rate * channels * bits // 8
    block_align = channels * bits // 8
    h = bytearray()
    h += b"RIFF"
    h += (36 + data_len).to_bytes(4, "little")
    h += b"WAVE"
    h += b"fmt "
    h += (16).to_bytes(4, "little")
    h += audio_format.to_bytes(2, "little")
    h += channels.to_bytes(2, "little")
    h += fmt.rate.to_bytes(4, "little")
    h += byte_rate.to_bytes(4, "little")
    h += block_align.to_bytes(2, "little")
    h += bits.to_bytes(2, "little")
    h += b"data"
    h += data_len.to_bytes(4, "little")
    return bytes(h)


def _strip_wav(data: bytes) -> bytes:
    """Return the PCM/mu-law payload of a RIFF buffer (or `data` unchanged)."""
    if len(data) < 12 or data[:4] != b"RIFF":
        return data
    idx = data.find(b"data")
    if idx == -1 or idx + 8 > len(data):
        return data
    return data[idx + 8:]


# --------------------------------------------------------------------------- #
# The two operations the gateway needs                                        #
# --------------------------------------------------------------------------- #
def decode_to_pcm16(data: bytes, fmt: MediaFormat, target_rate: int) -> bytes:
    """A VAIC userStream chunk in `fmt` -> PCM16 at `target_rate` (agent input)."""
    if fmt.wav:
        data = _strip_wav(data)
    if fmt.encoding == "mulaw":
        data = mulaw_decode(data)
    return resample_pcm16(data, fmt.rate, target_rate)


def encode_from_pcm16(pcm: bytes, src_rate: int, fmt: MediaFormat) -> bytes:
    """Agent PCM16 at `src_rate` -> a VAIC playStream chunk in `fmt`."""
    data = resample_pcm16(pcm, src_rate, fmt.rate)
    if fmt.encoding == "mulaw":
        data = mulaw_encode(data)
    if fmt.wav:
        data = _wav_header(len(data), fmt) + data
    return data
