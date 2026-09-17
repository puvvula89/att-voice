"""Translation directions: inbound audio from one leg -> translator -> playback on a leg."""
from __future__ import annotations

import asyncio
import logging

from bridge.channels import CallStart, InboundAudio, InboundEnd, TranslatedAudio, Transcript, TurnComplete
from bridge.metrics import rms

log = logging.getLogger("bridge")

_FRAME_24K = 960       # 20 ms of 24 kHz PCM16
PLAY_IDLE_S = 0.4      # close the playStream after this long without translated speech
SILENT_RMS = 50.0      # model output below this level is silence


class EventPump:
    """Reads a gateway's events in one long-lived task and fans them into a queue.

    Consumers can come and go (wait for start, wait for the agent, translate)
    without cancelling a read in progress, which would close the generator.
    While `discard_audio` is set, inbound audio is dropped.
    """

    def __init__(self, gateway):
        self._queue: asyncio.Queue = asyncio.Queue()
        self.discard_audio = False
        self._task = asyncio.create_task(self._run(gateway))

    async def _run(self, gateway):
        try:
            async for ev in gateway.events():
                if self.discard_audio and isinstance(ev, InboundAudio):
                    continue
                await self._queue.put(ev)
                if isinstance(ev, InboundEnd):
                    return
        except Exception as e:
            log.warning("event pump stopped: %r", e)
        await self._queue.put(InboundEnd())

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._queue.get()

    def close(self):
        self._task.cancel()


async def play_paced(gateway, pcm: bytes) -> None:
    """Stream audio in 20 ms frames at real-time speed, then close the playStream."""
    for off in range(0, len(pcm), _FRAME_24K):
        await gateway.send_audio(pcm[off:off + _FRAME_24K])
        await asyncio.sleep(0.02)
    await gateway.end_turn()


async def wait_for_start(gateway, events, greeting: bytes | None) -> CallStart | None:
    """Consume events until the call `start` activity; configure and answer the leg.

    VoiceAI Connect answers the call on the bot's first playStream, and needs
    barge-in so caller audio keeps flowing while translated audio plays.
    """
    async for ev in events:
        if isinstance(ev, CallStart):
            await gateway.configure_session()
            if greeting:
                await play_paced(gateway, greeting)
            return ev
        if isinstance(ev, InboundEnd):
            return None
    return None


async def run_direction(events, translator, out_gateway, metrics=None) -> None:
    """Pump one direction until the inbound leg ends or the translator stops."""
    await translator.open()
    idle: asyncio.TimerHandle | None = None
    loop = asyncio.get_running_loop()

    def arm_idle():
        # Live Translate streams continuously and may not mark turn ends; VAIC treats
        # an open playStream as the bot speaking, so close it when output pauses.
        nonlocal idle
        if idle:
            idle.cancel()
        idle = loop.call_later(PLAY_IDLE_S, lambda: asyncio.ensure_future(out_gateway.end_turn()))

    async def uplink():
        async for ev in events:
            if isinstance(ev, InboundAudio):
                if metrics:
                    metrics.on_inbound(ev.pcm)
                await translator.send_audio(ev.pcm)
            elif isinstance(ev, InboundEnd):
                return

    async def downlink():
        async for ev in translator.events():
            if isinstance(ev, TranslatedAudio):
                if metrics:
                    metrics.record_model_audio(ev.pcm)
                # Live Translate streams silence between utterances. Silence must not
                # open or extend a playStream, or VAIC withholds the caller's audio;
                # it is forwarded only inside an utterance that is already playing.
                if rms(ev.pcm) < SILENT_RMS:
                    if out_gateway.playing:
                        await out_gateway.send_audio(ev.pcm)
                    continue
                if metrics:
                    metrics.on_model_audio(ev.pcm)
                await out_gateway.send_audio(ev.pcm)
                if metrics:
                    metrics.on_forwarded()
                arm_idle()
            elif isinstance(ev, Transcript):
                if metrics:
                    metrics.on_transcript(ev.kind, ev.text, ev.language)
            elif isinstance(ev, TurnComplete):
                if idle:
                    idle.cancel()
                await out_gateway.end_turn()

    up = asyncio.create_task(uplink())
    down = asyncio.create_task(downlink())
    try:
        done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if not t.cancelled() and t.exception():
                log.error("direction task failed: %r", t.exception())
    finally:
        if idle:
            idle.cancel()
        up.cancel()
        down.cancel()
        await asyncio.gather(up, down, return_exceptions=True)
        await translator.close()
        if metrics:
            metrics.summary()
        await out_gateway.end_turn()


async def run_pair(caller_events, caller_gateway, agent_events, agent_gateway,
                   translator_to_agent, translator_to_caller, metrics_to_agent=None,
                   metrics_to_caller=None) -> None:
    """Cross two legs: caller speech plays to the agent, agent speech to the caller.
    When either leg ends, both directions stop."""
    a = asyncio.create_task(run_direction(caller_events, translator_to_agent, agent_gateway, metrics_to_agent))
    b = asyncio.create_task(run_direction(agent_events, translator_to_caller, caller_gateway, metrics_to_caller))
    try:
        await asyncio.wait({a, b}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (a, b):
            t.cancel()
        await asyncio.gather(a, b, return_exceptions=True)
