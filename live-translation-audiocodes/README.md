# Live Translation Bridge (POC)

A WebSocket bridge behind AudioCodes VoiceAI Connect / Live Hub that translates a call in real time using Gemini Live Translate. See `live-translation-poc-prd.md` for scope.

## Layout

| Path | Purpose |
|---|---|
| `bridge/server.py` | FastAPI app: `/audiocodes-ws` (Bot API WebSocket + connectivity check) |
| `bridge/audiocodes_gateway.py` | Bot API protocol: handshake, userStream in, playStream out, hangup |
| `bridge/audio_transcode.py` | Coder negotiation and PCM/μ-law conversion |
| `bridge/channels.py` | Transport and translator interfaces |
| `bridge/call.py` | Runs one translation direction |
| `bridge/echo.py` | M0 echo translator |
| `tests/` | Unit tests and a fake VoiceAI Connect client (`tests/smoke/`) |
| `docs/lab-inventory.md` | Lab configuration status |

## Run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # set AUDIOCODES_TOKEN
.venv/bin/python -m pytest -q
.venv/bin/uvicorn bridge.server:app --port 8080
.venv/bin/python tests/smoke/smoke_audiocodes.py   # in a second shell
```

Expose it to Live Hub:

```bash
ngrok http 8080
```

## Live Hub bot connection (M0)

| Setting | Value |
|---|---|
| Bot URL | `wss://<tunnel-host>/audiocodes-ws` |
| API type | WebSocket |
| Token | same value as `AUDIOCODES_TOKEN` |
| Voice streaming | enabled |
| directSTT / directTTS | `true` |

Call the number, speak, pause: you should hear yourself played back.
