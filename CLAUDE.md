# att-voice

Voice-agent reference project on Google ADK + the Gemini Live API. One numbered folder per use case, each independently runnable.

- **Module `01-phone-upgrade`** — voice phone-upgrade agent. Design: `docs/design/phone-upgrade-voice-agent.md`. Plan: `docs/plans/2026-06-03-phone-upgrade-voice-agent.md`.

## Conventions

- **ADK:** `google-adk>=2.0` (2.0 GA). 2.0 has breaking changes vs 1.x — verify import paths against the installed package, not memory.
- **Live model:** default is Vertex/ADC `gemini-live-2.5-flash-native-audio`. AI Studio (key) alternative: `gemini-3.1-flash-live-preview` (newest, but AI-Studio-only — not on Vertex yet). Env-driven via `LIVE_MODEL`.
- **TDD:** test-first for pure-Python code. Streaming/agent/relay/frontend are integration-verified, not unit-tested.
- **No tooling footprint in committed artifacts:** no co-author trailers, no tool/plugin names in paths, neutral professional naming. Outputs may be shared externally.

## Learnings

> High bar. Only record non-obvious gotchas worth never repeating (a moved 2.0 import, a required RunConfig field, a callback-ordering trap, an audio-format requirement). One concise line each. Not a changelog.

- **ADK 2.x `InMemorySessionService.create_session` is async** — must be `await`-ed (it returns a coroutine; using it unawaited gives `'coroutine' object has no attribute 'id'`). For sync contexts use `create_session_sync`. (Import-only smoke checks miss this; a live run catches it.)
- **`LiveRequestQueue.send_realtime` takes `types.Blob(data=bytes, mime_type=str)`** — pass raw PCM bytes wrapped in a `Blob`; it does not accept bare bytes.
- **Web Audio `ScriptProcessorNode` must be connected to `AudioContext.destination`** — even for capture-only use; without that connection the `onaudioprocess` callback never fires.
- **Gemini Live `send_realtime` PCM needs the rate in the mime type** — use `audio/pcm;rate=16000`; bare `audio/pcm` defaults to the wrong sample rate and input audio is garbled/ignored.
- **Vertex live model id differs from the Developer-API one** — Vertex/ADC: `gemini-live-2.5-flash-native-audio`; AI Studio key: `gemini-2.5-flash-native-audio-preview-12-2025`. Wrong-backend id = model-not-found.
- **Standalone uvicorn does not auto-load `.env` (adk web does)** — call `load_dotenv()` at the top of server.py BEFORE importing the agent module, or `LIVE_MODEL`/Vertex env vars are missing at agent import time.
- **`adk web` lists every subdirectory of AGENTS_DIR as an agent** — plain `adk web` from the module root shows `backend`/`frontend`/`tests` as bogus entries. Run `adk web <agent_folder>` (e.g. `adk web phone_upgrade`) pointing at the single agent folder for a clean one-agent list.
- **Browser playback `AudioContext` stays suspended until a user gesture** — model audio is silent even though mic capture works (capture is kept alive by the MediaStream). Resume the playback context from a click/keypress handler (a Start button); lazily creating it when audio arrives is too late.
- **genai serializes audio bytes as base64url, but browser `atob()` needs standard base64** — `inlineData.data` from a `model_dump_json` event uses `-`/`_`; `atob` throws `InvalidCharacterError`. Convert first: `b64.replace(/-/g,"+").replace(/_/g,"/")`. (Mic input is fine — `btoa` emits standard base64.)
- **Live-only models reject `generateContent`** — `gemini-live-2.5-flash-native-audio` only works via the Live API (`run_live`); typing text in `adk web` → `400 ... not supported in the generateContent API`. Test these models with voice/Live, not text.
- **Speaker audio feeds back into the mic and the model "hears itself"** — over laptop speakers the agent's own voice gets re-sent as user input and the flow auto-advances (model itself waits correctly; verified headless). Fix with half-duplex: stop sending mic frames while the agent is speaking (`isAgentSpeaking()` gate) + getUserMedia `echoCancellation`. Headphones also avoid it.
- **An on-connect greeting trigger fires whenever the WebSocket opens** — if the relay sends a `(call_start)` nudge on connect and the browser opens the WS at page load, the agent greets before the user's Start gesture (and the playback `AudioContext` is still suspended). Open the WebSocket *inside* the Start click handler, not at module load.
- **Live transcription streams deltas, then one cumulative final** — `event.output_transcription`/`input_transcription` arrive as fragments with `finished=False`, then a single `finished=True` event carrying the *whole* utterance. Append the deltas and **replace** on final; appending both double-renders the text.
- **`SpeechConfig` has no speaking-rate knob for native-audio Live** — only `voice_config` / `language_code` / `multi_speaker_voice_config` (the numeric `speaking_rate` is TTS-API-only). Tempo is steerable only via voice choice (`PrebuiltVoiceConfig.voice_name`, e.g. `Charon`) + prompt wording; playback is 24 kHz and correct, so it isn't the cause.
- **`python -m http.server` 304s stale ES modules during dev** — it honors `If-Modified-Since`, so an edited `client.js`/`components.js` is served from browser cache even after a hard refresh. Serve no-cache in dev (strip the conditional headers + send `Cache-Control: no-store`) or version-bump the import (`./client.js?v=N`).
- **ADK 2.1 `MCPToolset` is deprecated → use `McpToolset`** (lowercase `c`) from `google.adk.tools.mcp_tool`. Wire it `McpToolset(connection_params=StreamableHTTPConnectionParams(url=".../mcp"), tool_filter=[...])`. Default FastMCP port is 8000 — collides with the relay; run the MCP server on another port.
- **FastMCP tools that return a bare `dict` produce NO `structuredContent`** — ADK delivers the payload to `after_tool_callback` as `tool_response["content"][0]["text"]` (a JSON *string*). Parse that; don't read `structuredContent` (null unless the tool has a typed return model).
- **Agent-level `after_tool_callback` DOES fire for remote MCP tools** (the `tool` arg is an `McpTool` with `.name`). That's the seam for staging MCP results into `tool_context.state` — which the remote MCP process itself can't touch. Keep state-dependent tools (UI render / session-control) agent-local; let MCP serve only stateless data, with ids passed as args every call.
