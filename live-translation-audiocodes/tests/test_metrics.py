import array

from bridge.metrics import CallMetrics

_AUDIO = b"\x00\x00" * 480


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _chunk(value, ms=40):
    return array.array("h", [value] * (16 * ms)).tobytes()


def _quiet(m, ms):
    for _ in range(ms // 40):
        m.on_inbound(_chunk(0))


def test_output_after_speech_ends_is_attributed_to_that_utterance():
    clock = Clock()
    m = CallMetrics("c1", "caller-to-agent", silence_ms=200, record_dir=None, clock=clock)

    m.on_inbound(_chunk(0))
    clock.t = 1.0
    m.on_inbound(_chunk(3000))          # utterance 1 onset
    _quiet(m, 400)                      # utterance ends before any output
    clock.t = 2.2
    m.on_transcript("output", "hello", "en")
    clock.t = 2.4
    m.on_model_audio(_AUDIO)
    m.on_forwarded()
    clock.t = 2.5
    m.on_model_audio(_AUDIO)            # same burst: no new attribution

    clock.t = 3.0
    m.on_inbound(_chunk(3000))          # utterance 2 onset
    clock.t = 3.7
    m.on_model_audio(_AUDIO)            # new burst (gap >= 400 ms)
    m.on_forwarded()

    s = m.summary()
    assert s["utterances"] == 2
    assert s["ttfa_ms"]["values"] == [1400, 700]
    assert s["ttft_ms"]["values"] == [1200]
    assert s["first_send_ms"]["values"] == [1400, 700]


def test_output_without_speech_is_ignored():
    m = CallMetrics("c2", "caller-to-agent", record_dir=None, clock=Clock())
    m.on_model_audio(_AUDIO)
    assert m.summary() == {"utterances": 0}
