import array
import asyncio

from bridge.channels import TranslatedAudio, TurnComplete
from bridge.echo import EchoTranslator

_40MS = 640  # samples at 16 kHz


def _chunk(value):
    return array.array("h", [value] * _40MS).tobytes()


def _run(chunks):
    async def run():
        t = EchoTranslator(silence_ms=200)
        await t.open()
        for c in chunks:
            await t.send_audio(c)
        await t.close()
        return [ev async for ev in t.events()]

    return asyncio.run(run())


def test_continuous_stream_flushes_after_quiet_period():
    # Leading silence is dropped; speech + trailing silence plays back once.
    events = _run([_chunk(0)] * 5 + [_chunk(3000)] * 5 + [_chunk(0)] * 10)
    audio = b"".join(e.pcm for e in events if isinstance(e, TranslatedAudio))
    assert sum(isinstance(e, TurnComplete) for e in events) == 1
    # 5 speech chunks + 5 quiet chunks (200 ms) buffered = 400 ms at 24 kHz.
    assert abs(len(audio) - 19200) <= 8


def test_silence_only_produces_nothing():
    assert _run([_chunk(0)] * 30) == []
