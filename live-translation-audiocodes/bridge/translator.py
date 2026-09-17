"""Gemini Live Translate session for one translation direction.

Live Translate auto-detects the source language, so a direction is fully
described by its target language and `echo_target_language` (PRD §7.2).
"""
from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from bridge.channels import TranslatedAudio, Transcript, TurnComplete

log = logging.getLogger("bridge")

CHUNK_BYTES = 3200  # 100 ms of 16 kHz PCM16, per Google's latency guidance


class GeminiTranslator:
    def __init__(self, *, project: str, location: str, model: str,
                 target_language: str, echo_target_language: bool, voice: str = ""):
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model
        self._config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=target_language,
                echo_target_language=echo_target_language,
            ),
        )
        if voice:
            # Prebuilt voice instead of the model's voice replication (experimental
            # for Live Translate: accepted by the API, effect verified by listening).
            self._config.speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            )
        self._cm = None
        self._session = None
        self._pending = bytearray()
        self._closed = False

    async def open(self) -> None:
        self._cm = self._client.aio.live.connect(model=self._model, config=self._config)
        self._session = await self._cm.__aenter__()
        log.info("gemini session open model=%s target=%s",
                 self._model, self._config.translation_config.target_language_code)

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        self._pending.extend(pcm)
        while len(self._pending) >= CHUNK_BYTES:
            chunk = bytes(self._pending[:CHUNK_BYTES])
            del self._pending[:CHUNK_BYTES]
            await self._session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    async def events(self):
        # receive() ends after each turn_complete; loop to keep the session streaming.
        while not self._closed:
            async for msg in self._session.receive():
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    yield Transcript("input", sc.input_transcription.text,
                                     getattr(sc.input_transcription, "language_code", "") or "")
                if sc.output_transcription and sc.output_transcription.text:
                    yield Transcript("output", sc.output_transcription.text,
                                     getattr(sc.output_transcription, "language_code", "") or "")
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            yield TranslatedAudio(part.inline_data.data)
                if sc.turn_complete:
                    yield TurnComplete()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._cm is not None:
            try:
                await asyncio.wait_for(self._cm.__aexit__(None, None, None), 5)
            except Exception:
                pass
