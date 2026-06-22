"""TDD for the pure audio-transcode layer the AudioCodesGateway sits on.

VoiceAI Connect negotiates a coder (mu-law / linear PCM at 8/16/24 kHz); the ADK
agents speak 16 kHz PCM16 in and 24 kHz PCM16 out. These pure functions bridge
the two. Python 3.13+ dropped stdlib `audioop`, so this is hand-rolled — hence
the test bar.
"""
import array
import math

from relay.audio_transcode import (
    AGENT_IN_RATE,
    AGENT_OUT_RATE,
    MediaFormat,
    decode_to_pcm16,
    encode_from_pcm16,
    mulaw_decode,
    mulaw_encode,
    parse_format,
    resample_pcm16,
    select_formats,
)


def _pcm(samples: list[int]) -> bytes:
    return array.array("h", samples).tobytes()


def _samples(pcm: bytes) -> list[int]:
    a = array.array("h")
    a.frombytes(pcm)
    return list(a)


# --------------------------------------------------------------------------- #
# Format parsing                                                              #
# --------------------------------------------------------------------------- #
def test_parse_known_formats():
    assert parse_format("raw/lpcm16") == MediaFormat("raw/lpcm16", "lpcm16", 16000, False)
    assert parse_format("raw/lpcm16_8") == MediaFormat("raw/lpcm16_8", "lpcm16", 8000, False)
    assert parse_format("raw/lpcm16_24") == MediaFormat("raw/lpcm16_24", "lpcm16", 24000, False)
    assert parse_format("raw/mulaw") == MediaFormat("raw/mulaw", "mulaw", 8000, False)
    assert parse_format("wav/lpcm16") == MediaFormat("wav/lpcm16", "lpcm16", 16000, True)


def test_parse_unknown_returns_none():
    assert parse_format("audio/ogg") is None
    assert parse_format("") is None


# --------------------------------------------------------------------------- #
# Format selection (negotiation)                                              #
# --------------------------------------------------------------------------- #
def test_select_prefers_native_rates():
    # Full menu offered: caller-in wants 16k lpcm, play-out wants 24k lpcm —
    # both agent-native so no resampling.
    supported = [
        "raw/mulaw", "raw/lpcm16", "raw/lpcm16_8", "raw/lpcm16_24",
    ]
    user_fmt, play_fmt = select_formats(supported)
    assert user_fmt.name == "raw/lpcm16"      # 16k in = agent input rate
    assert play_fmt.name == "raw/lpcm16_24"   # 24k out = agent output rate


def test_select_telephony_only_falls_back():
    # A PSTN tenant offers only 8k mu-law: both directions use it (transcoded).
    user_fmt, play_fmt = select_formats(["raw/mulaw"])
    assert user_fmt.name == "raw/mulaw"
    assert play_fmt.name == "raw/mulaw"


def test_select_ignores_unknown_and_prefers_raw_over_wav():
    user_fmt, play_fmt = select_formats(["audio/ogg", "wav/lpcm16", "raw/lpcm16"])
    assert user_fmt.name == "raw/lpcm16"      # raw preferred over wav
    assert play_fmt.name == "raw/lpcm16"


def test_select_empty_defaults_to_lpcm16():
    user_fmt, play_fmt = select_formats([])
    assert user_fmt.name == "raw/lpcm16"
    assert play_fmt.name == "raw/lpcm16"


# --------------------------------------------------------------------------- #
# Resampling                                                                  #
# --------------------------------------------------------------------------- #
def test_resample_same_rate_is_identity():
    pcm = _pcm([0, 100, -100, 32767, -32768])
    assert resample_pcm16(pcm, 16000, 16000) == pcm


def test_resample_changes_length_by_ratio():
    pcm = _pcm([0] * 160)  # 10 ms @ 16k
    up = resample_pcm16(pcm, 16000, 24000)
    assert len(_samples(up)) == 240
    down = resample_pcm16(pcm, 24000, 8000)
    assert len(_samples(_pcm([0] * 240))) == 240
    assert len(_samples(resample_pcm16(_pcm([0] * 240), 24000, 8000))) == 80


def test_resample_preserves_constant_signal():
    pcm = _pcm([1000] * 100)
    out = _samples(resample_pcm16(pcm, 8000, 16000))
    assert all(abs(s - 1000) <= 1 for s in out)


def test_resample_preserves_endpoints_of_ramp():
    pcm = _pcm(list(range(0, 1000, 10)))  # rising ramp
    out = _samples(resample_pcm16(pcm, 16000, 24000))
    assert out[0] == 0
    assert abs(out[-1] - 990) <= 5


# --------------------------------------------------------------------------- #
# mu-law (G.711)                                                              #
# --------------------------------------------------------------------------- #
def test_mulaw_zero_anchor():
    # mu-law encodes silence to 0xFF (all-ones after the standard inversion).
    assert mulaw_encode(_pcm([0])) == b"\xff"


def test_mulaw_sign_distinguished():
    pos = mulaw_encode(_pcm([4000]))[0]
    neg = mulaw_encode(_pcm([-4000]))[0]
    assert (pos & 0x80) != (neg & 0x80)  # sign bit differs


def test_mulaw_reencode_is_idempotent():
    # mu-law is a quantizer: decoding a code then re-encoding yields the SAME
    # code. This is the exact correctness invariant (round-trip is lossy).
    # 0x7F is the lone exception — "negative zero": it decodes to linear 0, which
    # re-encodes to the positive-zero code 0xFF (a documented G.711 artifact).
    for code in range(256):
        if code == 0x7F:
            continue
        lin = mulaw_decode(bytes([code]))
        assert mulaw_encode(lin) == bytes([code])


def test_mulaw_roundtrip_tracks_signal():
    # A sine through encode->decode stays close in a relative sense.
    src = [int(8000 * math.sin(i / 5.0)) for i in range(200)]
    back = _samples(mulaw_decode(mulaw_encode(_pcm(src))))
    # mu-law step near these magnitudes is a few hundred; error stays bounded.
    assert max(abs(a - b) for a, b in zip(src, back)) < 600


# --------------------------------------------------------------------------- #
# Format decode/encode round-trips through the agent rates                    #
# --------------------------------------------------------------------------- #
def test_decode_lpcm16_native_is_passthrough_to_agent_rate():
    pcm16 = _pcm([0, 500, -500, 1000])
    fmt = parse_format("raw/lpcm16")  # already 16k
    out = decode_to_pcm16(pcm16, fmt, AGENT_IN_RATE)
    assert out == pcm16


def test_decode_8k_upsamples_to_16k():
    pcm8 = _pcm([100] * 80)  # 10 ms @ 8k
    fmt = parse_format("raw/lpcm16_8")
    out = decode_to_pcm16(pcm8, fmt, AGENT_IN_RATE)
    assert len(_samples(out)) == 160  # upsampled to 16k


def test_encode_24k_agent_audio_to_8k_mulaw():
    pcm24 = _pcm([2000] * 240)  # 10 ms @ 24k
    fmt = parse_format("raw/mulaw")
    out = encode_from_pcm16(pcm24, AGENT_OUT_RATE, fmt)
    assert len(out) == 80  # 10 ms @ 8k mu-law = 80 bytes (1 byte/sample)


def test_encode_24k_to_lpcm16_24_is_passthrough():
    pcm24 = _pcm([1, 2, 3, 4])
    fmt = parse_format("raw/lpcm16_24")
    assert encode_from_pcm16(pcm24, AGENT_OUT_RATE, fmt) == pcm24


def test_decode_strips_and_encode_adds_wav_header():
    pcm = _pcm([10, 20, 30, 40] * 50)
    wav_fmt = parse_format("wav/lpcm16")  # 16k, header
    framed = encode_from_pcm16(pcm, AGENT_IN_RATE, wav_fmt)
    assert framed[:4] == b"RIFF"
    # Decoding it back at the same rate recovers the PCM payload.
    out = decode_to_pcm16(framed, wav_fmt, AGENT_IN_RATE)
    assert out == pcm
