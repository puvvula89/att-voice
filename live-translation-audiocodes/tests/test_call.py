"""run_direction playback gating with fake gateway and translator."""
import array
import asyncio

import bridge.call as call
from bridge.channels import InboundEnd, TranslatedAudio

_SILENCE = bytes(960)
_SPEECH = array.array("h", [4000] * 480).tobytes()


class FakeGateway:
    def __init__(self):
        self.log = []
        self.playing = False

    async def events(self):
        await asyncio.sleep(0.6)
        yield InboundEnd()

    async def send_audio(self, pcm):
        if not self.playing:
            self.log.append("start")
            self.playing = True
        self.log.append("speech" if pcm == _SPEECH else "silence")

    async def end_turn(self):
        if self.playing:
            self.log.append("stop")
            self.playing = False

    async def end(self):
        await self.end_turn()


class FakeTranslator:
    def __init__(self, script):
        self._script = script

    async def open(self):
        pass

    async def send_audio(self, pcm):
        pass

    async def events(self):
        for item in self._script:
            if item == "wait":
                await asyncio.sleep(0.25)
            else:
                yield TranslatedAudio(item)
        await asyncio.sleep(10)

    async def close(self):
        pass


def _run(script):
    gw = FakeGateway()
    call.PLAY_IDLE_S = 0.1
    asyncio.run(call.run_direction(gw.events(), FakeTranslator(script), gw))
    return gw.log


def test_silence_alone_never_opens_playstream():
    assert _run([_SILENCE] * 20) == []


def test_speech_opens_silence_inside_forwarded_then_idle_closes():
    log = _run([_SILENCE, _SPEECH, _SILENCE, _SPEECH, "wait", _SILENCE, _SILENCE])
    assert log == ["start", "speech", "silence", "speech", "stop"]
