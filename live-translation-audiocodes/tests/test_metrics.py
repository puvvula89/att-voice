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


def test_speech_end_marks_when_the_speaker_stopped_not_when_silence_was_confirmed():
    """The model's own speed can only be read from the moment speech ended.

    `speech_end_ms` is stamped at the last chunk that carried voice, not at the
    point the silence window closed -- otherwise every utterance would carry the
    silence threshold as if the speaker were still talking through it.
    """
    clock = Clock()
    m = CallMetrics("c-end", "caller-to-agent", silence_ms=200, record_dir=None, clock=clock)

    clock.t = 1.0
    m.on_inbound(_chunk(3000))          # onset
    clock.t = 2.5
    m.on_inbound(_chunk(3000))          # still speaking, 1.5 s in
    clock.t = 2.6
    _quiet(m, 400)                      # silence closes the utterance

    clock.t = 3.0
    m.on_model_audio(_AUDIO)
    m.on_forwarded()

    s = m.summary()
    assert s["speech_ms"]["values"] == [1500]
    # Onset-based latency still measures the whole span; the model leg is the
    # difference between them.
    assert s["ttfa_ms"]["values"] == [2000]


def test_hangup_still_closes_the_last_turns_speech():
    """A call that ends before the silence window closes must keep its model figure.

    The silence branch never runs on the final turn when the caller hangs up, so
    without closing speech at the end that turn carries no `speech_ms` -- and on a
    short call that drops the whole call back to the onset-based number this stamp
    exists to replace.
    """
    clock = Clock()
    m = CallMetrics("c-hangup", "caller-to-agent", silence_ms=200, record_dir=None,
                    clock=clock)
    m.on_inbound(_chunk(3000))          # onset at 0.0
    clock.t = 2.0
    m.on_inbound(_chunk(3000))          # still carrying voice at 2.0
    clock.t = 2.5
    m.on_model_audio(_chunk(3000))
    m.on_forwarded()
    clock.t = 2.6                       # caller hangs up mid-silence-window

    s = m.summary()
    assert s["speech_ms"]["values"] == [2000]
    assert s["ttfa_ms"]["values"] == [2500]


def test_speech_end_is_absent_while_the_speaker_is_still_talking():
    clock = Clock()
    m = CallMetrics("c-open", "caller-to-agent", silence_ms=200, record_dir=None, clock=clock)
    clock.t = 1.0
    m.on_inbound(_chunk(3000))
    s = m.summary()
    assert "speech_ms" not in s
