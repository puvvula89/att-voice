# att-voice

Voice-agent reference project on Google ADK + the Gemini Live API. One numbered folder per use case, each independently runnable.

- **Module `01-phone-upgrade`** — voice phone-upgrade agent. Design: `docs/design/phone-upgrade-voice-agent.md`. Plan: `docs/plans/2026-06-03-phone-upgrade-voice-agent.md`.

## Conventions

- **ADK:** `google-adk>=2.0` (2.0 GA). 2.0 has breaking changes vs 1.x — verify import paths against the installed package, not memory.
- **Live model:** `gemini-2.5-flash-native-audio-preview-12-2025` (Developer API / `GOOGLE_API_KEY`); Vertex equivalent `gemini-live-2.5-flash-native-audio`.
- **TDD:** test-first for pure-Python code. Streaming/agent/relay/frontend are integration-verified, not unit-tested.
- **No tooling footprint in committed artifacts:** no co-author trailers, no tool/plugin names in paths, neutral professional naming. Outputs may be shared externally.

## Learnings

> High bar. Only record non-obvious gotchas worth never repeating (a moved 2.0 import, a required RunConfig field, a callback-ordering trap, an audio-format requirement). One concise line each. Not a changelog.

- **ADK 2.x `InMemorySessionService.create_session` is synchronous** — returns `Session` directly; `await`-ing it raises `TypeError` (draft had `await`).
- **`LiveRequestQueue.send_realtime` takes `types.Blob(data=bytes, mime_type=str)`** — pass raw PCM bytes wrapped in a `Blob`; it does not accept bare bytes.
- **`runner.run_live` accepts `session=` as an alternative to `user_id`+`session_id`** — can pass the already-created `Session` object directly instead of decomposing its IDs.
- **`model_dump_json` on `Event` uses `exclude_none` (pydantic kwarg), not `exclude_unset`** — both exist; use `exclude_none=True` to strip null fields from the wire payload.
